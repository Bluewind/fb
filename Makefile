VERSION:=$(shell git describe --dirty | sed 's/^v//; s/-/./g')
PREFIX=/usr
MANDIR=$(PREFIX)/share/man
BINDIR=$(PREFIX)/bin

all: fb

fb: fb.py
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	sed 's|@VERSION@|$(VERSION)|' $< > $@
	chmod 755 $@

clean:
	rm -f fb
	rm -rf dist

install: all
	install -dm755 $(DESTDIR)$(BINDIR)
	install -m755 fb $(DESTDIR)$(BINDIR)/fb
	install -dm755 $(DESTDIR)$(MANDIR)/man1
	install -m644 fb.1 $(DESTDIR)$(MANDIR)/man1/fb.1

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/fb
	rm -f $(DESTDIR)$(MANDIR)/man1/fb.1

dist: all
	@[ -n "$(VERSION)" ] || (echo "Error: version detection failed"; exit 1)
	mkdir -p dist/fb-$(VERSION)
	cp -a fb{,.py} fb.1 COPYING Makefile dist/fb-$(VERSION)
	sed -i 's/^VERSION:=.*$$/VERSION:='$(VERSION)'/' dist/fb-$(VERSION)/Makefile
	cd dist; tar -czf fb-$(VERSION).tar.gz fb-$(VERSION)

version:
	@echo $(VERSION)

.PHONY: all install clean uninstall version dist
