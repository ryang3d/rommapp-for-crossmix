import os
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen, build_opener, HTTPSHandler

import sdl2
from filesystem import Filesystem
from glyps import glyphs
from semver import Version
from status import Status


class Update:
    github_repo = "rommapp/muos-app"

    def __init__(self, ui):
        self.ui = ui
        self.status = Status()
        self.filesystem = Filesystem()
        self.current_version = self.get_current_version()
        self.download_percent = 0.0
        self.total_size = 0

    def get_current_version(self) -> str:
        """Read the version from __version__.py in the current directory."""
        version_file = "__version__.py"
        if not os.path.exists(version_file):
            print("__version__.py not found")
            return "0.0.0"

        with open(version_file, "r") as f:
            content = f.read()
            match = re.search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
            if match:
                return match.group(1)
            else:
                print("Failed to read version from __version__.py")
                return "0.0.0"

    def update_available(self, v1, v2) -> bool:
        v1 = Version.parse(v1)
        v2 = Version.parse(v2)

        return v1 < v2

    def _create_ssl_opener(self):
        """Create a URL opener with proper SSL certificate verification."""
        ssl_context = None
        cert_file = None
        
        # First, check if SSL_CERT_FILE environment variable is set
        if os.getenv("SSL_CERT_FILE"):
            env_cert_file = os.getenv("SSL_CERT_FILE")
            if os.path.exists(env_cert_file):
                cert_file = env_cert_file
        
        # If no env var, try to use certifi if available (provides bundled CA certificates)
        if not cert_file:
            try:
                import certifi
                cert_file = certifi.where()
            except ImportError:
                pass
        
        # If still no cert file, try common system certificate locations
        if not cert_file:
            common_cert_paths = [
                "/etc/ssl/certs/ca-certificates.crt",  # Debian/Ubuntu
                "/etc/pki/tls/certs/ca-bundle.crt",    # RHEL/CentOS/Fedora
                "/etc/ssl/ca-bundle.pem",              # Some systems
                "/usr/share/ssl/certs/ca-bundle.crt",  # Some older systems
            ]
            
            for cert_path in common_cert_paths:
                if os.path.exists(cert_path):
                    cert_file = cert_path
                    break
        
        # Create SSL context with the found certificate file, or use default
        if cert_file:
            ssl_context = ssl.create_default_context(cafile=cert_file)
        else:
            # Fallback to default context (should work if system certs are properly configured)
            ssl_context = ssl.create_default_context()
        
        https_handler = HTTPSHandler(context=ssl_context)
        return build_opener(https_handler)

    def get_latest_release_info(self) -> dict | None:
        url = f"https://api.github.com/repos/{self.github_repo}/releases/latest"
        try:
            request = Request(url, headers={"Accept": "application/vnd.github.v3+json"})
            opener = self._create_ssl_opener()
            with opener.open(request, timeout=5) as response:  # trunk-ignore(bandit/B310)
                data = response.read().decode("utf-8")
                import json

                return json.loads(data)
        except (HTTPError, URLError) as e:
            print(f"Failed to fetch latest release info: {e}")
            return None

    def download_update(self, url) -> bool:
        update_filename = os.path.basename(url)
        try:
            request = Request(url)
            opener = self._create_ssl_opener()
            with opener.open(request) as response:  # trunk-ignore(bandit/B310)
                self.total_size = int(response.getheader("Content-Length", 0)) or 1
                self.download_percent = 0.0
                downloaded_bytes = 0
                chunk_size = 1024

                with open(update_filename, "wb") as out_file:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        out_file.write(chunk)
                        downloaded_bytes += len(chunk)
                        self.download_percent = min(
                            100.0, (downloaded_bytes / self.total_size) * 100
                        )
                        self.ui.draw_loader(self.download_percent)
                        self.ui.draw_log(
                            text_line_1="Downloading update...",
                            text_line_2=f"{self.download_percent:.2f} / 100 % | ( {glyphs.download} {update_filename})",
                            background=True,
                        )
                        self.ui.render_to_screen()
                        sdl2.SDL_Delay(16)

                self.status.updating.clear()
                return True

        except (HTTPError, URLError) as e:
            print(f"Update download failed: {e}")
            self.status.updating.clear()
            if os.path.exists(update_filename):
                os.remove(update_filename)
            return False
