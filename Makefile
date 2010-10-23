all: fb.1

fb.1: fb.pod
	pod2man -c "" fb.pod fb.1

clean:
	rm fb.1

install:
	install -Dm755 fb $(DESTDIR)/usr/bin/fb
	install -Dm644 fb.1 $(DESTDIR)/usr/share/man/man1/fb.1

uninstall:
	rm $(DESTDIR)/usr/bin/fb
	rm $(DESTDIR)/usr/share/man/man1/fb.1
