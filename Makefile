VERSION:=$(shell git describe | sed 's/^v//')
MANDIR=/usr/share/man
BINDIR=/usr/bin

all: fb.1

fb.1: fb.pod
	pod2man -c "" fb.pod fb.1

clean:
	rm -f fb.1
	rm -rf dist

install: all
	install -Dm755 fb $(DESTDIR)$(BINDIR)/fb
	install -Dm644 fb.1 $(DESTDIR)$(MANDIR)/man1/fb.1

uninstall:
	rm -f $(DESTDIR)$(BINDIR)/fb
	rm -f $(DESTDIR)$(MANDIR)/man1/fb.1

dist: all
	mkdir -p dist/fb-$(VERSION)
	cp -a fb fb.pod fb.1 COPYING Makefile dist/fb-$(VERSION)
	sed -i 's/^VERSION=.*$$/VERSION="'$(VERSION)'"/' dist/fb-$(VERSION)/fb
	cd dist; tar -czf fb-$(VERSION).tar.gz fb-$(VERSION)

version:
	@echo $(VERSION)
