VERSION=`git describe | sed 's/^v//'`

all: fb.1

fb.1: fb.pod
	pod2man -c "" fb.pod fb.1

clean:
	rm -f fb.1
	rm -rf dist

install: all
	install -Dm755 fb $(DESTDIR)/usr/bin/fb
	install -Dm644 fb.1 $(DESTDIR)/usr/share/man/man1/fb.1
	install -Dm644 COPYING $(DESTDIR)/usr/share/licenses/fb/COPYING

uninstall:
	rm -f $(DESTDIR)/usr/bin/fb
	rm -f $(DESTDIR)/usr/share/man/man1/fb.1
	rm -f $(DESTDIR)/usr/share/licenses/fb/COPYING

dist: all
	mkdir -p dist/fb-$(VERSION)
	cp -a fb fb.pod fb.1 COPYING Makefile dist/fb-$(VERSION)
	sed -i 's/^VERSION=.*$$/VERSION="'$(VERSION)'"/' dist/fb-$(VERSION)/fb
	cd dist; tar -czf fb-$(VERSION).tar.gz fb-$(VERSION)

version:
	@echo $(VERSION)
