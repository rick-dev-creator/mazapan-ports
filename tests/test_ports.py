"""The helper's tests: what it makes of the kernel's tables, of processes,
of Docker's ports, and how far an address reaches.

    python3 -m unittest discover -s tests
"""

import importlib.machinery
import importlib.util
import os
import socket
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
loader = importlib.machinery.SourceFileLoader("ports", str(HERE / "ports.py.tmpl"))
spec = importlib.util.spec_from_loader("ports", loader)
ports = importlib.util.module_from_spec(spec)
loader.exec_module(ports)


def proc(argv, comm=None, uid=None):
    return {"pid": 4242, "comm": comm or os.path.basename(argv[0])[:15], "ppid": 1, "start": 1,
            "uid": ports.ME if uid is None else uid, "argv": argv, "cwd": ""}


class Addresses(unittest.TestCase):
    def test_ipv4(self):
        self.assertEqual(ports._ip("0100007F"), "127.0.0.1")
        self.assertEqual(ports._ip("00000000"), "0.0.0.0")

    def test_ipv6(self):
        self.assertEqual(ports._ip("00000000000000000000000001000000"), "::1")
        self.assertEqual(ports._ip("00000000000000000000000000000000"), "::")

    def test_ipv4_mapped(self):
        self.assertEqual(ports._ip("0000000000000000FFFF00000100007F"), "127.0.0.1")


class Reach(unittest.TestCase):
    def test_loopback(self):
        self.assertEqual(ports.reach_of(["127.0.0.1", "::1"], set()), "local")

    def test_wildcard(self):
        self.assertEqual(ports.reach_of(["127.0.0.1", "0.0.0.0"], set()), "network")
        self.assertEqual(ports.reach_of(["::"], set()), "network")

    def test_lan(self):
        self.assertEqual(ports.reach_of(["192.168.1.20"], set()), "network")

    def test_vpn(self):
        self.assertEqual(ports.reach_of(["100.101.102.103"], set()), "vpn")
        self.assertEqual(ports.reach_of(["10.8.0.2"], {"10.8.0.2"}), "vpn")
        self.assertEqual(ports.reach_of(["10.8.0.2", "192.168.1.20"], {"10.8.0.2"}), "network")


class Docker(unittest.TestCase):
    def test_ports(self):
        self.assertEqual(ports._docker_ports("0.0.0.0:8080->80/tcp, [::]:8080->80/tcp"),
                         [("0.0.0.0", 8080, "tcp"), ("::", 8080, "tcp")])

    def test_range_and_udp(self):
        self.assertEqual(ports._docker_ports("127.0.0.1:5000-5001->5000-5001/udp"),
                         [("127.0.0.1", 5000, "udp"), ("127.0.0.1", 5001, "udp")])

    def test_exposed_only(self):
        self.assertEqual(ports._docker_ports("6379/tcp"), [])


class Names(unittest.TestCase):
    def test_tools_over_interpreters(self):
        self.assertEqual(ports.name_of(proc(["/usr/bin/node", "/x/node_modules/.bin/vite"])), "vite")
        self.assertEqual(ports.name_of(proc(["python3", "-m", "uvicorn", "app:app"])), "uvicorn")
        self.assertEqual(ports.name_of(proc(["python3", "-m", "http.server", "8000"])), "http.server")
        self.assertEqual(ports.name_of(proc(["python", "manage.py", "runserver"])), "django")

    def test_dotnet(self):
        self.assertEqual(ports.name_of(proc(["dotnet", "watch", "run"])), "dotnet watch")
        self.assertEqual(ports.name_of(proc(["dotnet", "bin/Debug/net10.0/Orders.Api.dll"])), "Orders.Api")

    def test_cut_names(self):
        p = proc(["/usr/bin/qemu-system-x86_64", "-name", "vm"], comm="qemu-system-x86")
        self.assertEqual(ports.name_of(p), "qemu-system-x86_64")
        self.assertEqual(ports.name_of(proc(["/usr/bin/node", "server.js"], comm="node-MainThread")), "node")

    def test_short_cmd(self):
        self.assertTrue(ports.short_cmd([ports.HOME + "/x/run"]).startswith("~/x"))


class Watchers(unittest.TestCase):
    def test_watchers(self):
        self.assertTrue(ports._watches(proc(["dotnet", "watch", "run"]), None))
        self.assertTrue(ports._watches(proc(["python3", "-m", "uvicorn", "a:a", "--reload"]), None))
        self.assertTrue(ports._watches(proc(["node", "--watch", "server.js"]), None))
        self.assertTrue(ports._watches(proc(["/usr/bin/nodemon", "app.js"]), None))

    def test_never_a_shell_or_someone_else(self):
        self.assertFalse(ports._watches(proc(["bash"]), None))
        self.assertFalse(ports._watches(proc(["dotnet", "watch"], uid=ports.ME + 1), None))
        self.assertFalse(ports._watches(proc(["node", "server.js"]), None))


class Projects(unittest.TestCase):
    def test_nearest_marker(self):
        with tempfile.TemporaryDirectory(dir=ports.HOME) as d:
            root = Path(d) / "shop-api"
            (root / "src" / "Api").mkdir(parents=True)
            (root / "Shop.sln").touch()
            name, path = ports.project_of(str(root / "src" / "Api"))
            self.assertEqual(name, "shop-api")
            self.assertTrue(path.startswith("~/"))

    def test_outside_home(self):
        self.assertEqual(ports.project_of("/tmp"), ("", ""))


class Free(unittest.TestCase):
    def test_taken_then_free(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        try:
            self.assertIs(ports.bindable(port), False)
        finally:
            s.close()
        self.assertIs(ports.bindable(port), True)

    def test_next_free_skips_taken(self):
        self.assertNotIn(ports.next_free(20000, taken={20001, 20002}), (20001, 20002))


if __name__ == "__main__":
    unittest.main()
