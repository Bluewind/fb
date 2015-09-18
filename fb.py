#!/usr/bin/python

from enum import Enum
import argparse
import collections
import contextlib
import datetime
import getpass
import json
import locale
import os
import pycurl
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import xdg.BaseDirectory

from io import BytesIO

# Source: http://stackoverflow.com/a/434328/953022
def chunker(seq, size):
        return (seq[pos:pos + size] for pos in range(0, len(seq), size))

# Source: http://stackoverflow.com/a/8356620
def print_table(table):
    col_width = [max(len(x) for x in col) for col in zip(*table)]
    for line in table:
        print("| " + " | ".join("{:{}}".format(x, col_width[i])
                                for i, x in enumerate(line)) + " |")

@contextlib.contextmanager
def make_temp_directory():
    temp_dir = tempfile.mkdtemp()
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir)

class APIException(Exception):
    pass

class CURLWrapper:
    def __init__(self, config):
        c = pycurl.Curl()
        c.setopt(c.USERAGENT, config['useragent'])
        c.setopt(c.HTTPHEADER, [
            "Expect:",
            "Accept: application/json",
            ])

        if config["debug"]:
            c.setopt(c.VERBOSE, 1)

        self.config = config
        self.curl = c
        self.post = []
        self.progressBar = ProgressBar()
        self.serverConfig = None

    def __add_post(self, data):
        for item in data:
            for key, value in item.items():
                self.post.append((key, (pycurl.FORM_CONTENTS, value)))

    def getServerConfig(self):
        if self.serverConfig is None:
            self.serverConfig = CURLWrapper(self.config).send_get("/file/get_config")
        return self.serverConfig

    def upload_files(self, files):
        totalSize = 0
        chunks = [[]]
        currentChunkSize = 0
        currentChunk = 0
        rets = {
                "ids": [],
                "urls": [],
                }
        if len(files) > self.config["min_files_per_request_default"]:
            self.getServerConfig()

        for file in files:
            filesize = os.stat(file).st_size
            totalSize += filesize
            if  filesize > self.config["warnsize"]:
                self.getServerConfig()
                if filesize > self.serverConfig["upload_max_size"]:
                    raise APIException("File too big")

            if self.serverConfig is not None and (currentChunkSize + filesize > self.serverConfig["request_max_size"] \
                    or len(chunks[currentChunk]) >= self.serverConfig["max_files_per_request"]):
                currentChunkSize = 0
                currentChunk += 1
                chunks.append([])
            chunks[currentChunk].append(file)
            currentChunkSize += filesize

        self.progressBar.set_ulglobal(totalSize)

        for chunk in chunks:
            counter = 0
            for file in chunk:
                counter+=1
                self.post.append(
                    ("file["+str(counter)+"]", (pycurl.FORM_FILE, file))
                    )
            ret = self.send_post_progress("/file/upload", [])
            rets["ids"] += ret["ids"]
            rets["urls"] += ret["urls"]

        self.progressBar.reset()

        return rets

    def send_get(self, url):
        self.curl.setopt(pycurl.URL, self.config["api_url"] + url)
        return self.perform()

    def send_get_simple(self, url):
        self.curl.setopt(pycurl.URL, self.config["pastebin"] + url)
        return self.perform_simple()

    def send_post_progress(self, url, data = []):
        self.curl.setopt(pycurl.NOPROGRESS, 0)
        ret = self.send_post(url, data)
        self.curl.setopt(pycurl.NOPROGRESS, 1)
        return ret

    def send_post(self, url, data = []):
        self.curl.setopt(pycurl.URL, self.config["api_url"] + url)
        self.curl.setopt(pycurl.POST, 1)
        self.__add_post(data)

        self.addAPIKey()
        ret = self.perform()
        self.post = []
        return ret

    def addAPIKey(self):
        self.__add_post([{"apikey": self.config["apikey"]}])

    def perform_simple(self):
        b = BytesIO()
        self.curl.setopt(pycurl.HTTPPOST, self.post)
        self.curl.setopt(pycurl.WRITEFUNCTION, b.write)
        self.curl.setopt(pycurl.PROGRESSFUNCTION, self.progressBar.progress)
        #self.curl.setopt(pycurl.MAX_SEND_SPEED_LARGE, 200000)
        self.curl.perform()
        if self.config["debug"]:
            print(b.getvalue())

        return b.getvalue().decode("utf-8")

    def perform(self):
        response = self.perform_simple()
        try:
            result = json.loads(response)
        except ValueError:
            raise APIException("Invalid response:\n%s" % response)

        if result["status"] == "error":
            raise APIException("Request failed: %s" % result["message"])
        if result["status"] != "success":
            raise APIException("Request failed or invalid response")

        httpcode = self.curl.getinfo(pycurl.HTTP_CODE)
        if httpcode != 200:
            raise APIException("Invalid HTTP response code: %s" % httpcode)


        return result["data"]

class ProgressBar:

    def __init__(self):
        samplecount = 20
        self.progressData = {
                "lastUpdateTime": time.time(),
                "lastLineLength": 0,
                "ullast": 0,
                "ulGlobalTotal": 0,
                "ulGlobal": 0,
                "ulLastSample": 0,
                "samples":  collections.deque(maxlen=samplecount),
                }

    def set_ulglobal(self, value):
        self.progressData["ulGlobalTotal"] = value

    def reset(self):
        self.progressData["ulGlobalTotal"] = 0
        self.progressData["ulGlobal"] = 0

    def progress(self, dltotal, dlnow, ultotal, ulnow):
        data = self.progressData
        assert data["ulGlobalTotal"] > 0

        # update values here because if we carry one progress bar over multiple
        # requests we could miss update when running after the rate limiter
        uldiff = ulnow - data['ullast']
        if uldiff < 0:
            # when jumping to the next request we need to reset ullast
            data['ullast'] = 0
            return 0
        data["ulGlobal"] += uldiff
        data["ullast"] = ulnow

        # upload complete, clean up
        if data["ulGlobal"] >= data["ulGlobalTotal"]:
            sys.stderr.write("%s\r" % (" " * (data["lastLineLength"] + 1)))
            return 0

        if ulnow == 0:
            return 0

        # limit update rate
        t = time.time()
        timeSpent = t - data["lastUpdateTime"]
        if timeSpent < 0.1 and timeSpent > -1.0:
            return 0

        uldiff = data['ulGlobal'] - data['ulLastSample']
        data["lastUpdateTime"] = t
        data["samples"].append({
            "size": uldiff,
            "time": timeSpent,
            })
        data['ulLastSample'] = data['ulGlobal']

        sampleTotal = 0
        sampleTime = 0
        for i in data["samples"]:
            sampleTotal += i["size"]
            sampleTime += i["time"]

        ulspeed = 0
        eta = "stalling"

        if sampleTime > 0:
            ulspeed = sampleTotal / sampleTime

        if ulspeed > 0:
            timeRemaining = (data['ulGlobalTotal'] - data['ulGlobal']) / ulspeed
            eta = self.format_time(timeRemaining)

        output = "\r{}/s uploaded: {:.1f}% = {}; ETA: {}".format(
                self.format_bytes(ulspeed),
                data['ulGlobal'] * 100 / data['ulGlobalTotal'],
                self.format_bytes(data['ulGlobal']),
                str(eta)
                )

        outputlen = len(output)
        if data["lastLineLength"] > outputlen:
            output += " " * (data["lastLineLength"] - outputlen)
        sys.stderr.write(output)

        data["lastLineLength"] = outputlen

    def format_bytes(self, bytes):
        suffix = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]
        boundry = 2048.0
        for s in suffix:
            if bytes <= boundry and bytes >= -boundry:
                break
            bytes /= 1024.0

        if s == "B":
            return "{:.0f}{}".format(bytes, s)
        else:
            return "{:.2f}{}".format(bytes, s)

    def format_time(self, time):
        seconds = time % 60
        minutes = (time/60)%60
        hours = (time/60/60)

        if hours >= 1:
            return "{:.0f}:{:02.0f}:{:02.0f}".format(hours, minutes, seconds)
        else:
            return "{:02.0f}:{:02.0f}".format(minutes, seconds)


class Compressor:
    @staticmethod
    def gzip(file):
        subprocess.call(['gzip', '-n', file])
        return file + '.gz'

    @staticmethod
    def xz(file):
        subprocess.call(['xz', file])
        return file + '.xz'

class ConfigParser:
    def __init__(self, file):
        self.config = {}
        self.config["pastebin"] = "https://paste.xinu.at"
        self.config["clipboard_cmd"] = "xclip"
        if os.uname()[0] == "Darwin":
            self.config["clipboard_cmd"] = "pbcopy"
        self.config["apikey_file"] = os.path.join(xdg.BaseDirectory.xdg_config_home, "fb-client/apikey")

        self.parse(file)

        self.config["apikey_file"] = os.path.expandvars(self.config["apikey_file"])

    def parse(self, file):
        fh = open(file)
        for line in fh.readlines():
            matches = re.match('^(?P<key>[^=]+)=(?P<quotechar>"?)(?P<value>.+)(?P=quotechar)$', line)
            if matches != None:
                self.config[matches.group('key')] = matches.group('value')

    def get_config(self):
        return self.config

class FBClient:
    # TODO: update version with sed
    version = "2.0.alpha"
    modes = Enum("modes", [
            "upload",
            "delete",
            "get",
            "create_apikey",
            "display_version",
            "display_history",
            ])

    def __init__(self):
        pass

    def parseConfig(self, file):
        c = ConfigParser(file)
        self.config = c.get_config()
        self.config["api_url"] = self.config["pastebin"]+"/api/v2.0.0"
        self.config["warnsize"] = 10*1024*1024
        self.config["min_files_per_request_default"] = 5
        self.config["min_variables_per_request_default"] = 20
        self.config["apikey"] = open(self.config["apikey_file"]).read()
        self.config["useragent"] = "fb-client/%s" % self.version

    def run(self):
        defaultConfigFile = os.path.join(xdg.BaseDirectory.xdg_config_home, 'fb-client/config')

        parser = argparse.ArgumentParser(
                description="Upload/nopaste file(s)/stdin to paste.xinu.at and copy URL(s) to clipboard.")

        switches = parser.add_argument_group('switches').add_mutually_exclusive_group()
        switches.add_argument("-d", "--delete", dest="mode", action="store_const", const=self.modes.delete,
                help="Delete the IDs")
        switches.add_argument("-g", "--get", dest="mode", action="store_const", const=self.modes.get,
                help="Download the IDs and output on stdout (use with care!)")
        switches.add_argument("-u", "--upload", dest="mode", action="store_const", const=self.modes.upload,
                help="Upload files/stdin (default)")
        switches.add_argument("-a", "--create-apikey", dest="mode", action="store_const", const=self.modes.create_apikey,
                help="Create a new api key")
        switches.add_argument("-v", "--version", dest="mode", action="store_const", const=self.modes.display_version,
                help="Display the client version")
        switches.add_argument("-H", "--history", dest="mode", action="store_const", const=self.modes.display_history,
                help="Display an upload history")

        parser.add_argument("--config", action="store", default=defaultConfigFile,
                help="Use different config file")
        parser.add_argument("-D", "--debug", default=False, action="store_true",
                help="Enable debug output")

        upload_options = parser.add_argument_group('upload options')
        upload_options.add_argument("-t", "--tar", default=False, action="store_true",
                help="Upload a tar file containing all files (and directories)")
        upload_options.add_argument("-m", "--multipaste", default=False, action="store_true",
                help="create a multipaste")
        upload_options.add_argument("-n", "--name", default="stdin", action="store",
                help="File name to use for upload when reading from stdin (default: stdin)")
        upload_options.add_argument("-e", "--extension", default="", action="store",
                help="extension for default highlighting (e.g. \"diff\")")

        parser.add_argument("-c", "--compress", default=0, action="count",
                help="Compress the file being uploaded with gz or xz if used 2 times. "
                "When used in conjunction with -g this decompresses the download")

        parser.add_argument("args", metavar="ID|file|folder", nargs="*")

        self.args = parser.parse_args()

        self.parseConfig(self.args.config)

        self.config["debug"] = self.args.debug

        self.curlw = CURLWrapper(self.config)

        functions = {
                self.modes.upload: self.upload,
                self.modes.delete: self.delete,
                self.modes.get: self.get,
                self.modes.create_apikey: self.create_apikey,
                self.modes.display_version: self.display_version,
                self.modes.display_history: self.display_history,
                }
        if not self.args.mode:
            self.args.mode = self.modes.upload

        with make_temp_directory() as self.tempdir:
            functions[self.args.mode]()

    def makedirs(self, path):
        dirname = os.path.dirname(path)
        try:
            os.makedirs(dirname)
        except OSError as e:
            if not (os.path.exists(dirname) and os.path.isdir(dirname)):
                raise
            pass

    def create_temp_copy_path(self, file):
        dest = os.path.normpath(self.tempdir + "/" + file)
        self.makedirs(dest)
        return dest

    def handle_compression(self, file):
        if self.args.compress > 0:
            compressor = {
                1: Compressor.gzip,
                2: Compressor.xz,
            }
            return compressor[self.args.compress](file)
        else:
            return file

    def create_temp_copy(self, file):
        dest = self.create_temp_copy_path(file)
        open(dest, "w").write(open(file).read())
        return dest

    def upload_files(self, files):
        ids = []
        urls = []
        upload_files = []
        for file in files:
            if not os.path.exists(file):
                sys.stderr.write("Error: File \"%s\" is not readable/not found.\n" % file)
                return

            if os.stat(file)[6] == 0:
                file = self.create_temp_copy(file)

            upload_files.append(self.handle_compression(file))

        resp = self.curlw.upload_files(upload_files)
        ids = resp["ids"]
        urls = resp["urls"]

        if self.args.multipaste or len(ids) > 1:
            self.multipaste(ids)
        else:
            for url in urls:
                print(url)
            self.setClipboard(' '.join(urls))

    def setClipboard(self, content):
        p = subprocess.Popen([self.config['clipboard_cmd']], stdin=subprocess.PIPE)
        p.communicate(input=content.encode('utf-8'))

    def multipaste(self, ids):
        data = []
        for id in ids:
            data.append({"ids["+id+"]": id})

        resp = self.curlw.send_post("/file/create_multipaste", data)
        print(resp["url"])

    def upload(self):
        if self.args.tar:
            tarPath = os.path.join(self.tempdir, 'upload.tar')
            tar = tarfile.open(tarPath, 'w')
            for file in self.args.args:
                tar.add(file)
            tar.close()
            self.upload_files([tarPath])
            return

        if not self.args.args:
            tempfile = os.path.join(self.tempdir, os.path.basename(self.args.name))
            if sys.stdin.isatty():
                print("^C to exit, ^D to send")
            f = open(tempfile, "w")
            try:
                f.write(sys.stdin.read())
            except KeyboardInterrupt:
                sys.exit(130)
            finally:
                f.close()
            self.upload_files([tempfile])
            return
        else:
            self.upload_files(self.args.args)
            return

    def extractId(self, arg):
        arg = arg.replace(self.config['pastebin'], '')
        match = re.match('^([^/]+)', arg)
        id = match.group(0)
        return id

    def get(self):
        for arg in self.args.args:
            id = self.extractId(arg)
            resp = self.curlw.send_get_simple(id)
            print(resp)

    def delete(self):
        chunksize = self.config["min_variables_per_request_default"]
        if len(self.args.args) > self.config["min_variables_per_request_default"]:
            sc = self.curlw.getServerConfig()
            # -1 to leave space for api key
            chunksize = sc["max_input_vars"] - 1

        for args in chunker(self.args.args, chunksize):
            data = []
            for arg in args:
                id = self.extractId(arg)
                data.append({"ids["+id+"]": id})

            resp = self.curlw.send_post("/file/delete", data)
            if resp["errors"]:
                for item in resp["errors"].values():
                    print("Failed to delete \"%s\": %s" % (item["id"], item["reason"]))


    def display_history(self):
        timeFormat = '%a, %d %b %Y %H:%M:%S +0000'
        resp = self.curlw.send_post("/file/history")

        multipasteItems = resp['multipaste_items']
        if not multipasteItems:
            multipasteItems = {}

        items = resp['items']
        if not items:
            items = {}

        items = list(items.values())
        multipasteItems = list(multipasteItems.values())

        for item in multipasteItems:
            item['id'] = item['url_id']
            item['filename'] = '%s file(s)' % (len(item['items']))
            item['mimetype'] = ''
            item['hash'] = ''
            # sum filesize of all items
            item['filesize'] = str(sum([int(resp['items'][i]['filesize']) for i in item['items'].keys()]))
            items.append(item)

        items.sort(key=lambda s: s['date'])

        itemsTable = [['ID', 'Filename', 'Mimetype', 'Date', 'Hash', 'Size']]
        itemsTable += [[
            i['id'],
            i['filename'],
            i['mimetype'],
            datetime.datetime.fromtimestamp(int(i['date'])).strftime(timeFormat),
            i['hash'],
            i['filesize'
                ]] for i in items]
        print_table(itemsTable)

    def display_version(self):
        print(self.version)

    def get_input(self, prompt, display=True):
        sys.stdout.write(prompt)
        sys.stdout.flush()
        if not display:
            input = getpass.getpass('')
        else:
            input = sys.stdin.readline().strip()
        return input

    def create_apikey(self):
        hostname = os.uname()[1]
        localuser = getpass.getuser()
        data = []

        data.append({'username': self.get_input("Username: ")})
        data.append({'password': self.get_input("Password: ", display=False)})
        data.append({'comment': "fb-client %s@%s" % (localuser, hostname)})
        data.append({'access_level': "apikey"})

        resp = self.curlw.send_post('/user/create_apikey', data)

        self.makedirs(os.path.dirname(self.config['apikey_file']))
        open(self.config['apikey_file'], 'w').write(resp['new_key'])

if __name__ == '__main__':
    try:
        FBClient().run()
    except APIException as e:
        sys.stderr.write(str(e)+"\n")
        sys.exit(1)
