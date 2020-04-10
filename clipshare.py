#!/usr/bin/env python3
import signal
import time
import os
import re
import sys
import json
import struct
from socket import socket, AF_INET, SOCK_DGRAM, SOL_SOCKET, SO_BROADCAST
from time import sleep
from threading import Thread

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk

signal.signal(signal.SIGINT, signal.SIG_DFL)

NUM_TIMES_DO_TRANSFER = 7
BCAST_ADDR = ('255.255.255.255', 57475)
MSG_FORMAT = 'connect to me on tcp:{}'
MSG_REGEX = r'connect to me on tcp:(\d+)'
N_MAX_URIS = 50
FILE_TRANSFER_PORT = 57575

class FileTransferer:
    def server(self):
        sock = socket()
        sock.bind(('0.0.0.0', FILE_TRANSFER_PORT))
        sock.listen(1)
        while True:
            client, addr = sock.accept()
            length = struct.unpack("!I", client.recv(4))[0]
            path = client.recv(length)
            with open(path, "rb") as f:
                while True:
                    tmp = f.read(2048)
                    if not tmp:
                        break
                    client.send(tmp)
            client.close()


    @staticmethod
    def download_file(computer, there, here):
        #window = _get_active_window()
        there = there.encode("utf-8")
        sock = socket()
        sock.connect((computer, FILE_TRANSFER_PORT))
        with open(here, "wb") as f:
            sock.send(struct.pack("!I",len(there)))
            sock.send(there)
            while True:
                tmp = sock.recv(1024)
                if not tmp:
                    break
                f.write(tmp)
        sock.close()


class Client:
    def run(self):
        comp, msg = self._find_something_to_paste()
        self._put_in_clipboard(msg["text"])

    def paste_files_here(self):
        comp, msg = self._find_something_to_paste()
        paths = msg['uris']
        if len(paths) > N_MAX_URIS:
            print("Too many files to download {} > {}".format(len(paths), N_MAX_URIS))
            return False
        if not all(map(self._is_file_path, paths)):
            print("Not all uris are legal paths")
            return False

        for path in paths:
            path = path.replace("file://", "")
            print("Downloading {}... ".format(path), end='')
            name = os.path.basename(path)
            FileTransferer.download_file(comp, path, name)
            print('v')

        print(r"\ - Success - /")

    def _find_something_to_paste(self):
        sock = socket(AF_INET, SOCK_DGRAM)
        sock.bind(('', BCAST_ADDR[1]))
        data, addr = sock.recvfrom(100)
        data = data.decode('utf-8')
        print(data)
        match = re.search(MSG_REGEX, data)
        if not match:
            print("Bad packet !")
            return

        port = match.groups()[0]
        port = int(port)
        ip = addr[0]
        print("Found clip sharer at {}".format(ip))
        sharer = socket()
        sharer.connect((ip, port))

        data = b''
        while True:
            tmp = sharer.recv(1024)
            if not tmp:
                break
            data += tmp

        data = data.decode('utf-8')
        msg = json.loads(data)
        print(msg)
        return ip, msg

    @staticmethod
    def _put_in_clipboard(text):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(data, -1)
        clipboard.store()

    @staticmethod
    def _is_file_path(path):
        match = re.match(r'^file://[/\w\.\-]+$', path)
        if match and match.group() == path:
            return True
        return False


    @staticmethod
    def _get_active_window():
        cmd = r"xprop -id `xprop -root _NET_ACTIVE_WINDOW | grep -o -E '0x\w+'` _GTK_APPLICATION_ID WM_NAME"
        root = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
        stdout, stderr = root.communicate()

        m = re.search(r'^_GTK_APPLICATION_ID\(UTF8_STRING\) = "(.+)"', stdout)
        if not m:
            return None

        app = m.group(1)
        m = re.search(r'WM_NAME\(STRING\) = "(.+)"$', stdout)
        if not m:
            return None
        title = m.group(1)
        return app, title


class CopiedData:
    data = None
    counter = 0
    time = 0

    def _set_new(self, data):
        self.data = data
        self.counter = 1
        self.time = time.time()

    def reset(self):
        self.data = None
        self.counter = 0

    def update(self, data):
        if not self.data or self.data != data:
            self._set_new(data)
        elif self.data == data:
            t = time.time()
            if t - self.time > 0.35:
                self._set_new(data)
            else:
                self.counter += 1
                self.time = t

    def get_repeated_count(self):
        return self.counter

    def __str__(self):
        return "CopiedData[counter={}| data={}]".format(self.counter, self.data)


class Server:
    def __init__(self):
        self.clip = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.last = CopiedData()

    def transfer_listener(self, data, listener):
        port = listener.getsockname()[1]
        listener.listen(1)
        listener.settimeout(10)

        print("Listenning on tcp:{}".format(port))

        client, addr = listener.accept()
        print("New client connection from {}".format(addr))
        client.send(data.encode('utf-8'))
        client.close()

        listener.close()
        print("Done listenning on tcp:{}".format(port))


    def _do_transfer(self, data):
        listener = socket()
        listener.bind(('0.0.0.0', 0))
        port = listener.getsockname()[1]
        Thread(target=self.transfer_listener, args=(data, listener,)).start()

        sock = socket(AF_INET, SOCK_DGRAM)
        sock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)
        for i in range(20):
            msg = MSG_FORMAT.format(port)
            sock.sendto(msg.encode('utf-8'), BCAST_ADDR)
            sleep(0.5)


    def do_transfer(self, data, async=True):
        print("Beginning transfer")
        if async:
            Thread(target=self._do_transfer, args=(data,)).start()
        else:
            self._do_transfer(data)


    def handle_clipboard_change(self):
        self.last.update(text)
        print(self.last)
        if self.last.get_repeated_count() >= NUM_TIMES_DO_TRANSFER:
            self.do_transfer(json.dumps(self.build_message()), async)
            self.last.reset()

    def build_message(self):
        msg = {}
        text = self.clip.wait_for_text()
        msg['text'] = text
        uris = self.clip.wait_for_uris()
        if uris:
            msg['uris'] = uris
        return msg

    def server(self):
        def callback(self, *args):
            self.handle_clipboard_change()
        self.clip.connect('owner-change', callback)
        Gtk.main()

    def copy_now(self):
        self.do_transfer(json.dumps(self.build_message()), async=False)


def redirect():
    with open("/tmp/clipshare.log", "ab") as f:
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)


if __name__ == '__main__':
    if not sys.stdout.isatty():
        redirect()

    cmd = os.path.basename(sys.argv[0]) if len(sys.argv) == 1 else sys.argv[1]
    if   cmd == 'server-repeated-copies-based':
        Server().server()
    elif cmd == 'server-shortcut-based':
        Server().copy_now()
    elif cmd == 'client':
        Client().run()
    elif cmd in ['pastefile', 'clishpest']:
        Client().paste_files_here()
    elif cmd == 'file-transfer-server':
        FileTransferer().server()
