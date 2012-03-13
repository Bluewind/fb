VERSION:=$(shell git describe --dirty | sed 's/^v//; s/-/./g')
MANDIR=/usr/share/man
BINDIR=/usr/bin
LIBDIR=/usr/lib
MY_LIBDIR=$(LIBDIR)/fb-client
CC=cc
CFLAGS?=-O2
MY_CFLAGS=-std=c99 -Wall -Wextra -pedantic
LIBCURL:=$(shell pkg-config --silence-errors --libs --cflags libcurl)

ifdef LIBCURL
all: fb fb-helper
else
all: fb
endif

fb: fb.in
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	sed 's|@VERSION@|$(VERSION)|; s|@LIBDIR@|$(MY_LIBDIR)|' $< > $@
	chmod 755 $@

fb-helper: fb-helper.c
	$(CC) $(MY_CFLAGS) $(CFLAGS) $(LIBCURL) -DVERSION=\"$(VERSION)\" -o $@ $<

clean:
	rm -f fb fb-helper
	rm -rf dist

install:
	install -dm755 $(DESTDIR)$(BINDIR)
	install -m755 fb $(DESTDIR)$(BINDIR)/fb
ifdef LIBCURL
	install -dm755 $(DESTDIR)$(MY_LIBDIR)
	install -m755 fb-helper $(DESTDIR)$(MY_LIBDIR)/fb-helper
endif
	install -dm755 $(DESTDIR)$(MANDIR)/man1
	install -m644 fb.1 $(DESTDIR)$(MANDIR)/man1/fb.1

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/fb
	rm -rf $(DESTDIR)$(MY_LIBDIR)
	rm -f $(DESTDIR)$(MANDIR)/man1/fb.1

dist: all
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	mkdir -p dist/fb-$(VERSION)
	cp -a fb-helper.c fb{,.in} fb.1 COPYING Makefile dist/fb-$(VERSION)
	sed -i 's/^VERSION:=.*$$/VERSION:='$(VERSION)'/' dist/fb-$(VERSION)/Makefile
	cd dist; tar -czf fb-$(VERSION).tar.gz fb-$(VERSION)

version:
	@echo $(VERSION)

.PHONY: all install clean uninstall version dist
