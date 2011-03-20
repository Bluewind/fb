VERSION:=$(shell git describe --dirty | sed 's/^v//')
MANDIR=/usr/share/man
BINDIR=/usr/bin
LIBDIR=/usr/lib
CC=gcc
CFLAGS=-O2 -std=c99 -Wall -Wextra -pedantic

all: fb.1 fb fb-upload

fb: fb.in
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	sed 's|@VERSION@|$(VERSION)|; s|@LIBDIR@|$(LIBDIR)|' fb.in > fb
	chmod 755 fb

fb.c: fb.c.in
	sed 's/@VERSION@/$(VERSION)/' fb.c.in > fb.c

fb-upload: fb.c
	$(CC) $(CFLAGS) -lcurl -lm -o fb-upload fb.c

fb.1: fb.pod
	pod2man -c "" fb.pod fb.1

clean:
	rm -f fb.1 fb fb.c fb-upload
	rm -rf dist

install: all
	install -Dm755 fb $(DESTDIR)$(BINDIR)/fb
	install -Dm755 fb-upload $(DESTDIR)$(LIBDIR)/fb-upload
	install -Dm644 fb.1 $(DESTDIR)$(MANDIR)/man1/fb.1

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/fb
	rm -f $(DESTDIR)$(LIBDIR)/fb-upload
	rm -f $(DESTDIR)$(MANDIR)/man1/fb.1

dist: all
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	mkdir -p dist/fb-$(VERSION)
	cp -a fb fb.c fb.in fb.pod fb.1 COPYING Makefile dist/fb-$(VERSION)
	sed -i 's/^VERSION:=.*$$/VERSION:="'$(VERSION)'"/' dist/fb-$(VERSION)/Makefile
	cd dist; tar -czf fb-$(VERSION).tar.gz fb-$(VERSION)

version:
	@echo $(VERSION)

.PHONY: all install clean uninstall version dist
