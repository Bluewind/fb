VERSION:=$(shell git describe --dirty | sed 's/^v//; s/-/./g')
MANDIR=/usr/share/man
BINDIR=/usr/bin
LIBDIR=/usr/lib
CC=cc
CFLAGS?=-O2 -std=c99 -Wall -Wextra -pedantic
LIBCURL:=$(shell pkg-config --silence-errors --libs --cflags libcurl)

all: fb.1 fb fb-helper

fb: fb.in
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	sed 's|@VERSION@|$(VERSION)|; s|@LIBDIR@|$(LIBDIR)|' $< > $@
	chmod 755 $@

ifdef LIBCURL
fb-helper: fb-helper.c
	$(CC) $(CFLAGS) $(LIBCURL) -DVERSION=\"$(VERSION)\" -o $@ $<
else
fb-helper: fb-helper.sh.in
	@echo "libcurl not found. using shell helper..."
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	sed 's|@VERSION@|$(VERSION)|; s|@LIBDIR@|$(LIBDIR)|' $< > $@
	chmod 755 $@
endif

fb.1: fb.pod
	pod2man -c "" $< $@

clean:
	rm -f fb.1 fb fb-helper
	rm -rf dist

install: all
	install -Dm755 fb $(DESTDIR)$(BINDIR)/fb
	install -Dm755 fb-helper $(DESTDIR)$(LIBDIR)/fb-helper
	install -Dm644 fb.1 $(DESTDIR)$(MANDIR)/man1/fb.1

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/fb
	rm -f $(DESTDIR)$(LIBDIR)/fb-helper
	rm -f $(DESTDIR)$(MANDIR)/man1/fb.1

dist: all
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	mkdir -p dist/fb-$(VERSION)
	cp -a fb-helper.c fb{,.in} fb.pod fb.1 COPYING Makefile dist/fb-$(VERSION)
	sed -i 's/^VERSION:=.*$$/VERSION:='$(VERSION)'/' dist/fb-$(VERSION)/Makefile
	cd dist; tar -czf fb-$(VERSION).tar.gz fb-$(VERSION)

version:
	@echo $(VERSION)

.PHONY: all install clean uninstall version dist
