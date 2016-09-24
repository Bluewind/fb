#!/usr/bin/env python

from __future__ import print_function
import argparse
import collections
import contextlib
import datetime
import errno
import getpass
import gzip
import json
import locale
import lzma
import os
import pycurl
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import xdg.BaseDirectory

from io import BytesIO

class ApikeyNotFoundException(Exception):
    pass

class Enum(set):
    def __getattr__(self, name):
        if name in self:
            return name
        raise AttributeError

# Source: http://stackoverflow.com/a/434328/953022
def chunker(seq, size):
        return (seq[pos:pos + size] for pos in range(0, len(seq), size))

# Source: http://stackoverflow.com/a/8356620
def print_table(table):
    col_width = [max(len(x) for x in col) for col in zip(*table)]
    for line in table:
        print("| " + " | ".join("{:{}}".format(x, col_width[i])
                                for i, x in enumerate(line)) + " |")

# Source: http://stackoverflow.com/a/14981125
def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

def humanize_bytes(num):
    suffix = ["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]
    boundary = 2048.0

    for unit in suffix:
        if abs(num) < boundary:
            break
        num /= 1024.0

    if unit == "B":
        format = "%.0f%s"
    else:
        format = "%.2f%s"

    return format % (num, unit)

@contextlib.contextmanager
def make_temp_directory():
    temp_dir = tempfile.mkdtemp()
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir)

class APIException(Exception):
    def __init__(self, message, error_id):
        super().__init__(message)
        self.error_id = error_id

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
                self.post.append((key, (pycurl.FORM_CONTENTS, value.encode('utf-8'))))

    def getServerConfig(self):
        if self.serverConfig is None:
            self.serverConfig = CURLWrapper(self.config).send_get("/file/get_config")
        return self.serverConfig

    def upload_files(self, files):
        """
        Upload files if f.should_upload() for f in files is true.

        Args:
            files: List of File objects
        Returns:
            List of updated File objects
        """
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
            if file.should_upload():
                filesize = os.stat(file.path).st_size
                totalSize += filesize
                if  filesize > self.config["warnsize"]:
                    self.getServerConfig()
                    if filesize > self.serverConfig["upload_max_size"]:
                        raise APIException("File too big: %s" % (file.path), "client-internal/file-too-big")

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
            if chunk:
                for file in chunk:
                    counter+=1
                    self.post.append(
                        ("file["+str(counter)+"]", (pycurl.FORM_FILE, file.path.encode('utf-8')))
                        )
                ret = self.send_post_progress("/file/upload", [])
                rets["ids"] += ret["ids"]
                rets["urls"] += ret["urls"]
                assert len(ret["ids"]) == len(ret["urls"])
                assert len(ret["ids"]) == len(chunk)
                for new_id, new_url, existing in zip(ret["ids"], ret["urls"], chunk):
                    existing.id = new_id
                    existing.url = new_url

        self.progressBar.reset()

        return files

    def send_get(self, url):
        self.curl.setopt(pycurl.URL, self.config["api_url"] + url)
        return self.perform()

    def send_get_simple(self, url):
        self.curl.setopt(pycurl.URL, self.config["pastebin"] + "/" + url)
        return self.perform_simple()

    def send_post_progress(self, url, data = []):
        self.curl.setopt(pycurl.NOPROGRESS, 0)
        ret = self.send_post(url, data)
        self.curl.setopt(pycurl.NOPROGRESS, 1)
        return ret

    def send_post_noauth(self, url, data = []):
        self.curl.setopt(pycurl.URL, self.config["api_url"] + url)
        self.curl.setopt(pycurl.POST, 1)
        self.__add_post(data)

        ret = self.perform()
        self.post = []
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
        assert self.config['apikey']
        self.__add_post([{"apikey": self.config["apikey"]}])

    def perform_simple(self):
        b = BytesIO()
        self.curl.setopt(pycurl.HTTPPOST, self.post)
        self.curl.setopt(pycurl.WRITEFUNCTION, b.write)
        self.curl.setopt(pycurl.PROGRESSFUNCTION, self.progressBar.progress)
        self.curl.perform()

        if self.config["debug"]:
            print(b.getvalue())

        return b.getvalue().decode("utf-8")

    def perform(self):
        response = self.perform_simple()

        try:
            result = json.loads(response)
        except ValueError:
            raise APIException("Invalid response:\n%s" % response, "client-internal/invalid-response")

        if result["status"] == "error":
            raise APIException("Request failed: %s" % result["message"], result['error_id'])
        if result["status"] != "success":
            raise APIException("Request failed or invalid response", "client-internal/invalid-response")

        httpcode = self.curl.getinfo(pycurl.HTTP_CODE)
        if httpcode != 200:
            raise APIException("Invalid HTTP response code: %s" % httpcode, "client-internal/invalid-response")


        return result["data"]

    def dl_file(self, url, path):
        # TODO: this is duplicated in __init__ (well mostly)
        c = pycurl.Curl()
        c.setopt(c.USERAGENT, self.config['useragent'])
        c.setopt(c.HTTPHEADER, [
            "Expect:",
            ])

        if self.config["debug"]:
            c.setopt(c.VERBOSE, 1)

        outfp = open(path, 'wb')
        try:
            c.setopt(c.URL, url)
            c.setopt(c.WRITEDATA, outfp)
            c.perform()
        finally:
            outfp.close()
            c.close()

class ProgressBar:

    def __init__(self):
        samplecount = 20
        self.display_progress = True
        if not sys.stderr.isatty():
            self.display_progress = False

        self.progressData = {
                "lastUpdateTime": time.time(),
                "ullast": 0,
                "ulGlobalTotal": 0,
                "ulGlobal": 0,
                "ulLastSample": 0,
                "samples":  collections.deque(maxlen=samplecount),
                }

    def set_ulglobal(self, value):
        self.progressData["ulGlobalTotal"] = value

    def reset(self):
        self.progressData["ulGlobalTotal"] = -1
        self.progressData["ulGlobal"] = 0

    def progress(self, dltotal, dlnow, ultotal, ulnow):
        data = self.progressData
        assert data["ulGlobalTotal"] > -1

        if not self.display_progress:
            return

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
            sys.stderr.write("\r\033[K")
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

        sys.stderr.write("\r{}/s uploaded: {:.1f}% = {}; ETA: {}\033[K".format(
                self.format_bytes(ulspeed),
                data['ulGlobal'] * 100 / data['ulGlobalTotal'],
                self.format_bytes(data['ulGlobal']),
                str(eta)
                ))

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
    def gzip(src, dst):
        dst += '.gz'
        with open(src, 'rb') as f_in, gzip.open(dst, 'wb') as f_out:
            f_out.writelines(f_in)
        return dst

    @staticmethod
    def xz(src, dst):
        dst += '.xz'
        with open(src, 'rb') as f_in, lzma.open(dst, 'wb') as f_out:
            f_out.writelines(f_in)
        return dst

class ConfigParser:
    def __init__(self, file, ignoreMissing=False):
        self.config = {}
        self.config["pastebin"] = "https://paste.xinu.at"
        self.config["clipboard_cmd"] = "xclip"
        if os.uname()[0] == "Darwin":
            self.config["clipboard_cmd"] = "pbcopy"
        self.config["apikey_file"] = os.path.join(xdg.BaseDirectory.xdg_config_home, "fb-client/apikey")

        self._parse(file, ignoreMissing=ignoreMissing)

        self.config["apikey_file"] = os.path.expandvars(self.config["apikey_file"])

    def _parse(self, file, ignoreMissing=False):
        try:
            fh = open(file)
        except OSError as e:
            if ignoreMissing:
                if e.errno == errno.ENOENT:
                    return
            raise
        except FileNotFoundError:
            if ignoreMissing:
                return

        with fh:
            for line in fh:
                matches = re.match('^(?P<key>[^=]+)=(?P<quotechar>"?)(?P<value>.+)(?P=quotechar)$', line)
                if matches != None:
                    self.config[matches.group('key')] = matches.group('value')

    def get_config(self):
        return self.config

class FBClient:
    version = "@VERSION@"
    if version.startswith('@'):
        version = 'unknown-version'

    modes = Enum([
            "upload",
            "delete",
            "get",
            "create_apikey",
            "display_version",
            "display_history",
            ])

    def __init__(self):
        pass

    def loadConfig(self):
        defaultConfigFile = os.path.join(xdg.BaseDirectory.xdg_config_home, 'fb-client/config')

        if self.args.config is None:
            self.parseConfig(defaultConfigFile, ignoreMissing=True)
        else:
            self.parseConfig(self.args.config)

    def parseConfig(self, file, ignoreMissing=False):
        c = ConfigParser(file, ignoreMissing=ignoreMissing)
        self.config = c.get_config()
        self.config["api_url"] = self.config["pastebin"]+"/api/v2.0.0"
        self.config["warnsize"] = 10*1024*1024
        self.config["min_files_per_request_default"] = 5
        self.config["min_variables_per_request_default"] = 20
        self.config["useragent"] = "fb-client/%s" % self.version

        # this needs to be at the end because during handling of the exception
        # the values above are used
        try:
            with open(self.config["apikey_file"]) as apikeyfile:
                self.config["apikey"] = apikeyfile.read()
        except FileNotFoundError:
            raise ApikeyNotFoundException()


    def run(self):
        signal.signal(signal.SIGINT, self.handle_ctrl_c)

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

        parser.add_argument("--config", action="store", default=None,
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

        parser.add_argument("args", metavar="file|dir|id://ID|URL", nargs="*")

        self.args = parser.parse_args()

        try:
            self.loadConfig()
        except ApikeyNotFoundException:
            if self.args.mode != self.modes.create_apikey:
                if sys.stdin.isatty():
                    eprint("No API key found, creating a new one")
                    self.config["debug"] = self.args.debug
                    self.curlw = CURLWrapper(self.config)
                    self.create_apikey()
                    self.curlw = None
                    self.loadConfig()
                else:
                    eprint("No API key found. Please run fb -a to create one")
                    sys.exit(1)

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

    def handle_ctrl_c(self, signal, frame):
        print("\nReceived signal, aborting!")
        sys.exit(1)

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
            return compressor[self.args.compress](file, self.create_temp_copy_path(file))
        else:
            return file

    def handle_directory(self, path):
        if os.path.isdir(path):
            return self.create_tarball(path)

        return path

    def create_tarball(self, path):
        compression = {
                0: "",
                1: "gz",
                2: "xz",
                }
        extension = "." + '.'.join(["tar", compression[self.args.compress]])
        tarball_path = os.path.normpath(self.tempdir + "/" + self.args.name + extension)
        tar = tarfile.open(tarball_path, "w:" + compression[self.args.compress])
        tar.add(path)
        tar.close()

        return tarball_path


    def create_temp_copy(self, file):
        dest = self.create_temp_copy_path(file)
        open(dest, "w").write(open(file).read())
        return dest

    def upload_files(self, files):
        """
        Upload files and create multipaste if multiple files are uploaded.

        Args:
            files: List of File objects to upload
        """
        upload_files = []
        for file in files:
            if file.should_upload():
                if not os.path.exists(file.path):
                    sys.stderr.write("Error: File \"%s\" is not readable/not found.\n" % file.path)
                    return

                if os.stat(file.path)[6] == 0:
                    file.path = self.create_temp_copy(file.path)

                if os.path.isdir(file.path):
                    file.path = self.create_tarball(file.path)
                else:
                    file.path = self.handle_compression(file.path)

            upload_files.append(file)

        resp = self.curlw.upload_files(upload_files)

        if self.args.multipaste or len(resp) > 1:
            resp = self.multipaste([f.id for f in resp])
            urls = [resp["url"]]
        else:
            urls = [f.url for f in resp]

        for url in urls:
            print(url)
        self.setClipboard(' '.join(urls))

    def setClipboard(self, content):
        try:
            with open('/dev/null', 'w') as devnull:
                p = subprocess.Popen([self.config['clipboard_cmd']], stdin=subprocess.PIPE, stdout=devnull, stderr=devnull)
                p.communicate(input=content.encode('utf-8'))
        except OSError as e:
            if e.errno == errno.ENOENT:
                return
            raise
        except FileNotFoundError:
            return

    def multipaste(self, ids):
        data = []
        for id in ids:
            data.append({"ids["+id+"]": id})

        resp = self.curlw.send_post("/file/create_multipaste", data)
        return resp

    def upload(self):
        if self.args.tar:
            for arg in self.args.args:
                if re.match('https?://', arg):
                    sys.stderr.write("Error: --tar does not support URLs as arguments")
                    return

            tarPath = os.path.join(self.tempdir, 'upload.tar')
            tar = tarfile.open(tarPath, 'w')
            for file in self.args.args:
                tar.add(file)
            tar.close()
            self.upload_files([File(tarPath)])
            return

        if not self.args.args:
            tempfile = os.path.join(self.tempdir, os.path.basename(self.args.name))
            if sys.stdin.isatty():
                print("^C to exit, ^D to send")
            f = open(tempfile, "wb")
            try:
                f.write(sys.stdin.buffer.read())
            except KeyboardInterrupt:
                sys.exit(130)
            finally:
                f.close()
            self.upload_files([File(tempfile)])
            return
        else:
            files = [self.containerize_arg(arg) for arg in self.args.args]
            self.upload_files(files)
            return

    def containerize_arg(self, arg):
        if re.match('id://', arg):
            id = arg.replace('id://', '')
            return File(id=id)
        if arg.startswith(self.config['pastebin']):
            return File(id=self.extractId(arg))
        if re.match('https?://', arg):
            outfile = os.path.join(self.tempdir, os.path.basename(arg.strip("/")))
            self.curlw.dl_file(arg, outfile)
            return File(outfile)

        return File(arg)


    def extractId(self, arg):
        arg = arg.replace(self.config['pastebin'], '')
        arg = arg.strip('/')
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

        uniqueSize = dict()
        for item in items:
            uniqueSize[item['hash']] = int(item['filesize'])

        totalSize = sum([v for v in uniqueSize.values()])

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
            humanize_bytes(int(i['filesize']))
                ] for i in items]
        print_table(itemsTable)

        print("\n")
        print("Total sum of your distinct uploads: %s" % (humanize_bytes(totalSize)))
        print("Total number of uploads (excluding multipastes): %s" % (len(resp['items'])))
        print("Total number of multipastes: %s" % (len(multipasteItems)))

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

        while True:
            data.append({'username': self.get_input("Username: ")})
            data.append({'password': self.get_input("Password: ", display=False)})
            data.append({'comment': "fb-client %s@%s" % (localuser, hostname)})
            data.append({'access_level': "apikey"})

            try:
                resp = self.curlw.send_post_noauth('/user/create_apikey', data)
                # break out of while loop on success
                break
            except APIException as e:
                if e.error_id == 'user/login-failed':
                    eprint(e)
                    eprint("\nPlease try again:")
                    continue
                else:
                    raise


        self.makedirs(self.config['apikey_file'])
        with open(self.config['apikey_file'], 'w') as outfile:
            outfile.write(resp['new_key'])

class File:
    path = None
    id = None
    paste_url = None

    def __init__(self, path=None, id=None):
        self.path = path
        self.id = id

    def should_upload(self):
        return self.id is None

if __name__ == '__main__':
    try:
        FBClient().run()
    except APIException as e:
        sys.stderr.write(str(e)+"\n")
        sys.exit(1)
