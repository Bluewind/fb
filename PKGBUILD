# Maintainer: Florian "Bluewind" Pritz <flo@xssn.at>

pkgname=fb-client
pkgver=2.0.3.r6.g56aea98
pkgrel=1
pkgdesc="Client for paste.xinu.at"
arch=("any")
url="https://paste.xinu.at"
license=('GPL3')
depends=('python' 'python-pycurl' 'python-xdg')
optdepends=(
  'xclip: automatically copy the URL into the clipboard on X11'
  'wl-clipboard: automatically copy the URL into the clipboard on wayland'
)
source=("git+https://git.server-speed.net/users/flo/fb#branch=dev")
md5sums=('SKIP')
validpgpkeys=("CFA6AF15E5C74149FC1D8C086D1655C14CE1C13E")

pkgver() {
  cd "$srcdir/fb"
  git describe --long | sed 's/^v//;s/\([^-]*-g\)/r\1/;s/-/./g'
}

build() {
  cd "$srcdir/fb"

  make
}

package() {
  cd "$srcdir/fb"

  make DESTDIR="$pkgdir" install
}

# vim:set ts=2 sw=2 et:
