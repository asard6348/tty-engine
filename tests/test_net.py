import math
import os
import socket
import struct
import threading
import time
import tracemalloc
import unittest
import zlib

os.environ.setdefault("COLUMNS", "100")
os.environ.setdefault("LINES", "40")

from ttyengine import scene as engine_scene
from ttyengine.components import joint
from ttyengine.launcher import Session
from ttyengine.net import (ConnectError, NetError, Node, ProtocolError, Ref, Sync, TcpLink, TcpListener,
                           UdpEndpoint, dumps, loads)
from ttyengine.net import node as node_module
from ttyengine.net.transport import MAX_FRAME

LOCAL = "127.0.0.1"


def pump(items, condition=None, timeout=5.0, spin=0.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        for item in items:
            item.update()
        if condition is not None and condition():
            return True
        time.sleep(0.001)
    return condition() if condition is not None else True


def linked(host, guest, protocol, items):
    link = guest.connect((LOCAL, host.listen[protocol]), protocol, wait=False)
    ok = pump(items, lambda: link.peer is not None and host.peers.get(guest.id) is not None)
    assert ok, "connection was not established"
    return link


class CodecTests(unittest.TestCase):
    def test_round_trip(self):
        value = {"a": [1, -2, 3.5, "é", b"z", None, True, False, (1, (2, 3)), {1, 2}], "n": -10 ** 30, "": {}}
        self.assertEqual(loads(dumps(value)), value)

    def test_types_are_kept(self):
        out = loads(dumps([(1, 2), [1, 2], 1, 1.0, True]))
        self.assertIsInstance(out[0], tuple)
        self.assertIsInstance(out[1], list)
        self.assertIs(type(out[2]), int)
        self.assertIs(type(out[3]), float)
        self.assertIs(out[4], True)

    def test_references(self):
        thing = object()
        data = dumps([thing, thing], lambda v: 7 if v is thing else None)
        self.assertEqual(loads(data), [Ref(7), Ref(7)])

    def test_unsupported_values_raise(self):
        with self.assertRaises(NetError):
            dumps(lambda: None)
        with self.assertRaises(NetError):
            dumps(object())

    def test_malformed_data_raises(self):
        for data in (b"", b"\x05\x09ab", b"\x7f", dumps(1) + b"x"):
            with self.assertRaises(ProtocolError):
                loads(data)

    def test_subclasses_and_nesting_limit(self):
        class Point(tuple):
            pass

        self.assertEqual(loads(dumps(Point((1, 2)))), (1, 2))
        deep = []
        for _ in range(100):
            deep = [deep]
        with self.assertRaises(NetError):
            dumps(deep)


class TransportTests(unittest.TestCase):
    def test_tcp_frames(self):
        listener = TcpListener(LOCAL, 0)
        client = TcpLink.dial((LOCAL, listener.port))
        server = None
        end = time.monotonic() + 5
        while server is None and time.monotonic() < end:
            client.update(time.monotonic())
            found = listener.accept()
            server = found[0] if found else None
        self.assertIsNotNone(server)
        big = bytes(range(256)) * 4000
        client.send(b"one")
        client.send(big)
        client.send(b"")
        got = []
        while len(got) < 3 and time.monotonic() < end:
            client.update(time.monotonic())
            server.update(time.monotonic())
            got += server.recv()
        self.assertEqual(got, [b"one", big, b""])
        client.close()
        while server.alive and time.monotonic() < end:
            server.update(time.monotonic())
        self.assertFalse(server.alive)
        server.close()
        listener.close()

    def test_udp_reliable_with_loss(self):
        server = UdpEndpoint(LOCAL, 0, accept=True)
        client = UdpEndpoint(LOCAL, 0)
        server.loss = client.loss = 0.3
        link = client.connect((LOCAL, server.port))
        payloads = [b"a" * 5000, b"b" * 10, b"c" * 70000]
        for item in payloads:
            link.send(item)
        theirs = None
        got = []
        end = time.monotonic() + 20
        while len(got) < 3 and time.monotonic() < end:
            now = time.monotonic()
            for fresh in server.update(now):
                theirs = fresh
            client.update(now)
            if theirs is not None:
                got += theirs.recv()
            time.sleep(0.001)
        self.assertEqual(got, payloads)
        server.close()
        client.close()

    def test_udp_unreliable_is_latest_wins(self):
        server = UdpEndpoint(LOCAL, 0, accept=True)
        client = UdpEndpoint(LOCAL, 0)
        link = client.connect((LOCAL, server.port))
        theirs = None
        end = time.monotonic() + 5
        while theirs is None and time.monotonic() < end:
            now = time.monotonic()
            found = server.update(now)
            theirs = found[0] if found else None
            client.update(now)
        while not link.opened and time.monotonic() < end:
            client.update(time.monotonic())
        link.send(b"x", reliable=False)
        link.send(b"y", reliable=False)
        got = []
        while len(got) < 2 and time.monotonic() < end:
            server.update(time.monotonic())
            got += theirs.recv()
        self.assertEqual(got, [b"x", b"y"])
        server.close()
        client.close()

    def test_bad_address(self):
        with self.assertRaises(NetError):
            TcpLink.dial("nonsense")


class NodeTests(unittest.TestCase):
    def tearDown(self):
        for node in getattr(self, "nodes", []):
            node.close()

    def make(self, *names, **kwargs):
        self.nodes = [Node(name, **kwargs) for name in names]
        return self.nodes

    def test_star_with_relay(self):
        for protocol in ("tcp", "udp"):
            host, a, b = self.make("host", "a", "b")
            host.host(0, LOCAL, protocol)
            linked(host, a, protocol, self.nodes)
            linked(host, b, protocol, self.nodes)
            self.assertTrue(pump(self.nodes, lambda: len(a.members) == 2 and len(b.members) == 2))
            got = []
            b.on("chat", lambda peer, data: got.append((peer.name, data)))
            a.send("chat", {"hello": [1, 2]})
            self.assertTrue(pump(self.nodes, lambda: got))
            self.assertEqual(got, [("a", {"hello": [1, 2]})])
            self.assertEqual(a.hostid, host.id)
            self.assertFalse(a.peers.get(b.id))
            left = []
            b.on("@leave", lambda peer: left.append(peer.name))
            a.close()
            self.assertTrue(pump([host, b], lambda: left == ["a"] and a.id not in b.members))
            for node in self.nodes:
                node.close()

    def test_direct_message_and_broadcast(self):
        host, a = self.make("host", "a")
        host.host(0, LOCAL, "tcp")
        linked(host, a, "tcp", self.nodes)
        got = []
        a.on("one", lambda peer, data: got.append(("one", data)))
        a.on("all", lambda peer, data: got.append(("all", data)))
        host.send("one", 1, to=a.id)
        host.send("all", 2)
        self.assertTrue(pump(self.nodes, lambda: len(got) == 2))
        self.assertEqual(sorted(got), [("all", 2), ("one", 1)])

    def test_large_payload_is_compressed_and_intact(self):
        host, a = self.make("host", "a")
        host.host(0, LOCAL, "udp")
        linked(host, a, "udp", self.nodes)
        got = []
        host.on("big", lambda peer, data: got.append(data))
        blob = {"text": "ab" * 50000, "n": list(range(2000))}
        a.send("big", blob)
        self.assertTrue(pump(self.nodes, lambda: got))
        self.assertEqual(got[0], blob)

    def test_mesh_connects_every_pair(self):
        for protocol in ("tcp", "udp"):
            nodes = [Node(str(i), mesh=True) for i in range(3)]
            self.nodes = nodes
            for node in nodes:
                node.host(0, LOCAL, "both")
            linked(nodes[0], nodes[1], protocol, nodes)
            linked(nodes[0], nodes[2], protocol, nodes)
            self.assertTrue(pump(nodes, lambda: all(len(n.peers) == 2 for n in nodes)))
            self.assertFalse(any(n.relay for n in nodes))
            for node in nodes:
                node.close()

    def test_password_and_duplicate_rejection(self):
        host, good, bad = self.make("host", "good", "bad")
        host.password = "secret"
        good.password = "secret"
        host.host(0, LOCAL, "tcp")
        linked(host, good, "tcp", self.nodes)
        with self.assertRaises(ConnectError):
            bad.connect((LOCAL, host.listen["tcp"]), "tcp", timeout=0.3)
        self.assertEqual(list(host.peers), [good.id])

    def test_connect_failure(self):
        listener = TcpListener(LOCAL, 0)
        port = listener.port
        listener.close()
        (node,) = self.make("lonely")
        with self.assertRaises(ConnectError):
            node.connect((LOCAL, port), "tcp", timeout=1.0)

    def test_auto_protocol_falls_back(self):
        host, a = self.make("host", "a")
        host.host(0, LOCAL, "udp")
        stop = threading.Event()
        worker = threading.Thread(target=host.serve, kwargs={"interval": 0.001, "until": stop.is_set})
        worker.start()
        try:
            peer = a.connect((LOCAL, host.listen["udp"]), "auto", timeout=3.0)
            self.assertEqual(peer.protocol, "udp")
            with self.assertRaises(NetError):
                a.connect((LOCAL, host.listen["udp"]), "auto", wait=False)
        finally:
            stop.set()
            worker.join()


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.nodes = []
        self.syncs = []

    def tearDown(self):
        for node in self.nodes:
            node.close()

    def pair(self, protocol="tcp", **kwargs):
        host, guest = Node("host"), Node("guest")
        self.nodes = [host, guest]
        host.host(0, LOCAL, protocol)
        hs, gs = Sync(host, **kwargs), Sync(guest, **kwargs)
        self.syncs = [hs, gs]
        return host, guest, hs, gs

    def connect(self, host, guest, protocol="tcp"):
        linked(host, guest, protocol, self.syncs)

    def test_scene_objects_replicate_both_ways(self):
        for protocol in ("tcp", "udp"):
            host, guest, hs, gs = self.pair(protocol)
            a, b = engine_scene.Scene(), engine_scene.Scene()
            hs.share(a, "arena")
            gs.share(b, "arena")
            ball = a.obj().create("\x1b[31mHI\x1b[0m", 3, 4, xvel=2, bounciness=0.5)
            self.connect(host, guest, protocol)
            self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
            twin = b.objs[0]
            self.assertEqual(twin.transform._vbase, "\x1b[31mHI\x1b[0m")
            self.assertEqual((twin.transform.x, twin.transform.y, twin.physics.xvel, twin.physics.bounciness),
                             (3, 4, 2, 0.5))
            self.assertTrue(twin._remote)
            ball.transform.x = 9
            ball.transform.fg = (1, 2, 3)
            a.gravity = (0, -2)
            self.assertTrue(pump(self.syncs, lambda: twin.transform.x == 9 and b.gravity == (0, -2)))
            self.assertEqual(twin.transform.fg, (1, 2, 3))
            mine = b.obj().create("Z", 1, 1)
            self.assertTrue(pump(self.syncs, lambda: len(a.objs) == 2))
            self.assertEqual(a.objs[1].transform.htext, "Z")
            self.assertFalse(mine._remote)
            mine.transform.y = 5
            self.assertTrue(pump(self.syncs, lambda: a.objs[1].transform.y == 5))
            ball.discard()
            self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
            mine.discard()
            self.assertTrue(pump(self.syncs, lambda: len(a.objs) == 0))
            for node in self.nodes:
                node.close()

    def test_late_joiner_receives_snapshot(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena")
        for i in range(20):
            a.obj().create("#", i, i, mass=3)
        pump(self.syncs, timeout=0.05)
        gs.share(b, "arena")
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 20))
        self.assertEqual(sorted(o.transform.x for o in b.objs), list(range(20)))

    def test_snapshot_arrives_before_mount(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena")
        a.obj().create("#", 1, 2)
        self.connect(host, guest)
        pump(self.syncs, timeout=0.2)
        self.assertEqual(len(b.objs), 0)
        gs.share(b, "arena")
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))

    def test_star_relays_between_clients(self):
        host = Node("host")
        host.host(0, LOCAL, "tcp")
        one, two = Node("one"), Node("two")
        self.nodes = [host, one, two]
        syncs = [Sync(n) for n in self.nodes]
        self.syncs = syncs
        scenes = [engine_scene.Scene() for _ in range(3)]
        for sync, scene in zip(syncs, scenes):
            sync.share(scene, "arena")
        linked(host, one, "tcp", syncs)
        linked(host, two, "tcp", syncs)
        scenes[1].obj().create("A", 1, 1)
        self.assertTrue(pump(syncs, lambda: all(len(s.objs) == 1 for s in scenes)))
        moved = scenes[1].objs[0]
        moved.transform.x = 42
        self.assertTrue(pump(syncs, lambda: scenes[2].objs[0].transform.x == 42 and scenes[0].objs[0].transform.x == 42))

    def test_mesh_replication_without_relay(self):
        nodes = [Node(str(i), mesh=True) for i in range(3)]
        self.nodes = nodes
        for node in nodes:
            node.host(0, LOCAL, "tcp")
        syncs = [Sync(n) for n in nodes]
        self.syncs = syncs
        scenes = [engine_scene.Scene() for _ in range(3)]
        for sync, scene in zip(syncs, scenes):
            sync.share(scene, "arena")
        linked(nodes[0], nodes[1], "tcp", syncs)
        linked(nodes[0], nodes[2], "tcp", syncs)
        self.assertTrue(pump(syncs, lambda: all(len(n.peers) == 2 for n in nodes)))
        scenes[2].obj().create("M", 3, 3)
        self.assertTrue(pump(syncs, lambda: all(len(s.objs) == 1 for s in scenes)))
        scenes[2].objs[0].transform.x = 8
        self.assertTrue(pump(syncs, lambda: all(s.objs[0].transform.x == 8 for s in scenes)))

    def test_variable_selection(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena", vars={"obj": ("transform.x", "transform.y", "hp")}, exclude=("transform.y",))
        gs.share(b, "arena", vars={"obj": ("transform.x", "transform.y", "hp")}, exclude=("transform.y",))
        item = a.obj().create("#", 1, 1, hp=10, xvel=3)
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
        twin = b.objs[0]
        item.transform.x = 5
        item.transform.y = 6
        item.hp = 7
        item.physics.xvel = 9
        self.assertTrue(pump(self.syncs, lambda: twin.transform.x == 5 and getattr(twin, "hp", None) == 7))
        self.assertEqual(twin.transform.y, 0)
        self.assertIsNone(getattr(twin, "physics", None))

    def test_single_variable_sharing(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        one = a.obj().create("#", 1, 1)
        two = b.obj().create("#", 0, 0)
        hs.share((one, "x"), name="hero")
        gs.share((two, "x"), name="hero")
        self.connect(host, guest)
        one.transform.x = 11
        one.transform.y = 12
        self.assertTrue(pump(self.syncs, lambda: two.transform.x == 11))
        self.assertEqual(two.transform.y, 0)

    def test_variable_ownership(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena")
        gs.share(b, "arena")
        ball = a.obj().create("O", 0, 0, xvel=0)
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
        twin = b.objs[0]
        hs.transfer(ball, guest.id, vars=("physics.xvel",))
        self.assertTrue(pump(self.syncs, lambda: gs._var_owner(gs.entity(twin), "physics", "xvel") == guest.id))
        twin.physics.xvel = 6
        self.assertTrue(pump(self.syncs, lambda: ball.physics.xvel == 6))
        ball.physics.xvel = 99
        ball.transform.x = 4
        self.assertTrue(pump(self.syncs, lambda: twin.transform.x == 4))
        self.assertEqual(twin.physics.xvel, 6)

    def test_entity_ownership_transfer(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena")
        gs.share(b, "arena")
        ball = a.obj().create("O", 0, 0)
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
        twin = b.objs[0]
        with self.assertRaises(NetError):
            gs.transfer(twin, host.id)
        hs.transfer(ball, guest.id)
        self.assertTrue(pump(self.syncs, lambda: gs.is_owner(twin)))
        self.assertTrue(ball._remote)
        self.assertFalse(twin._remote)
        twin.transform.x = 3
        self.assertTrue(pump(self.syncs, lambda: ball.transform.x == 3))

    def test_non_owner_cannot_write(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena")
        gs.share(b, "arena")
        ball = a.obj().create("O", 0, 0)
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
        b.objs[0].transform.x = 77
        pump(self.syncs, timeout=0.3)
        self.assertEqual(ball.transform.x, 0)

    def test_unreliable_state_converges_under_loss(self):
        host, guest, hs, gs = self.pair("udp", resync=0.05)
        for endpoint in list(host._udp.values()) + [guest._client_endpoint(2)]:
            endpoint.loss = 0.3
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena", reliable=False)
        gs.share(b, "arena", reliable=False)
        items = [a.obj().create("o", i, 0) for i in range(30)]
        self.connect(host, guest, "udp")
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 30, timeout=15))
        for step in range(5):
            for i, item in enumerate(items):
                item.transform.x = 100 + step + i
        self.assertTrue(pump(self.syncs, lambda: [o.transform.x for o in b.objs] ==
                             [104 + i for i in range(30)], timeout=15))

    def test_frozen_and_live_replicas(self):
        for mode in ("frozen", "live"):
            host, guest, hs, gs = self.pair(replicas=mode)
            a, b = engine_scene.Scene(), engine_scene.Scene()
            for scene in (a, b):
                scene.gravity = (0, -1)
            hs.share(a, "arena")
            gs.share(b, "arena")
            a.obj().create("o", 0, 10, dynamic=False)
            self.connect(host, guest)
            self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
            twin = b.objs[0]
            self.assertEqual(twin._remote, mode == "frozen")
            twin.physics.dynamic = True
            for _ in range(30):
                b.tick()
            if mode == "frozen":
                self.assertEqual(twin.transform.y, 10)
            else:
                self.assertLess(twin.transform.y, 10)
            for node in self.nodes:
                node.close()

    def test_orphans_policy(self):
        for policy in ("drop", "adopt", "keep"):
            host = Node("host")
            host.host(0, LOCAL, "tcp")
            one, two = Node("one"), Node("two")
            self.nodes = [host, one, two]
            syncs = [Sync(n, orphans=policy) for n in self.nodes]
            self.syncs = syncs
            scenes = [engine_scene.Scene() for _ in range(3)]
            for sync, scene in zip(syncs, scenes):
                sync.share(scene, "arena")
            linked(host, one, "tcp", syncs)
            linked(host, two, "tcp", syncs)
            scenes[1].obj().create("A", 1, 1)
            self.assertTrue(pump(syncs, lambda: all(len(s.objs) == 1 for s in scenes)))
            one.close()
            remaining = [host, two]
            rs = [syncs[0], syncs[2]]
            self.assertTrue(pump(remaining + rs, lambda: one.id not in two.members and one.id not in host.members))
            pump(rs, timeout=0.2)
            expected = 0 if policy == "drop" else 1
            self.assertEqual((len(scenes[0].objs), len(scenes[2].objs)), (expected, expected))
            if policy == "adopt":
                winner = min(host.id, two.id)
                owner = rs[0] if winner == host.id else rs[1]
                scene = scenes[0] if winner == host.id else scenes[2]
                self.assertTrue(owner.is_owner(scene.objs[0]))
                self.assertFalse(scene.objs[0]._remote)
            for node in self.nodes:
                node.close()

    def test_session_world_scene_obj_chain(self):
        host, guest, hs, gs = self.pair()
        s1 = Session(sound=False, inp=False)
        s2 = Session(sound=False, inp=False)
        hs.share(s1, "game")
        gs.share(s2, "game")
        world = s1.World()
        world.scene.obj().create("W", 2, 2)
        s1.pausephysics = True
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(s2.worlds) == 1 and len(s2.worlds[0].scene.objs) == 1))
        mirrored = s2.worlds[0]
        self.assertTrue(s2.pausephysics)
        world.scene.gravity = (0, -3)
        world.pause = True
        self.assertTrue(pump(self.syncs, lambda: mirrored.scene.gravity == (0, -3) and mirrored.pause))
        s1.World()
        self.assertTrue(pump(self.syncs, lambda: len(s2.worlds) == 2))
        world.unregister()
        self.assertTrue(pump(self.syncs, lambda: len(s2.worlds) == 1))
        self.assertEqual(len(s2.worlds[0].scene.objs), 0)

    def test_joints_replicate(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena")
        gs.share(b, "arena")
        first = a.obj().create("#", 0, 0)
        second = a.obj().create("#", 3, 0)
        first.set(joint)
        first.joint.attach(second, "rod")
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 2 and
                             all(getattr(o, "joint", None) is not None for o in b.objs)))
        pump(self.syncs, timeout=0.2)
        parent, child = b.objs
        self.assertIn(parent, list(child.joint.joints))
        edge = child.joint._edges[id(parent)]
        self.assertIs(edge.origin.obj, parent)
        self.assertEqual(child.joint.kind, second.joint.kind)

    def test_unshareable_values_are_skipped_not_fatal(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena")
        gs.share(b, "arena")
        item = a.obj().create("#", 0, 0, force={"affect": lambda o: True, "strength": 2})
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
        self.assertIn(("obj", "force", "affect"), hs.skipped)
        self.assertEqual(b.objs[0].force.force, 2)

    def test_explicit_unshareable_variable_raises(self):
        host, guest, hs, gs = self.pair()
        a = engine_scene.Scene()
        item = a.obj().create("#", 0, 0, force={"affect": lambda o: True})
        self.connect(host, guest)
        hs.share(item, "thing", vars=("force.affect",))
        with self.assertRaises(NetError):
            hs.update()

    def test_ignore_and_filter(self):
        host, guest, hs, gs = self.pair()
        a, b = engine_scene.Scene(), engine_scene.Scene()
        hs.share(a, "arena", filter=lambda o: o.transform.htext != "x")
        gs.share(b, "arena")
        a.obj().create("x", 0, 0)
        hidden = a.obj().create("y", 1, 1)
        a.obj().create("z", 2, 2)
        hs.ignore(hidden)
        self.connect(host, guest)
        self.assertTrue(pump(self.syncs, lambda: len(b.objs) == 1))
        self.assertEqual(b.objs[0].transform.htext, "z")

    def test_attach_runs_inside_a_world(self):
        host, guest, hs, gs = self.pair()
        s1 = Session(sound=False, inp=False)
        s2 = Session(sound=False, inp=False)
        w1, w2 = s1.World(), s2.World()
        hs.share(w1, "arena")
        gs.share(w2, "arena")
        hs.attach(w1)
        gs.attach(s2)
        w1.scene.obj().create("A", 4, 4)
        self.connect(host, guest)
        for _ in range(400):
            for world in (w1, w2):
                for handle in world.ordered_handles():
                    handle.func("update")()
                world.scene.tick()
                for handle in world.ordered_handles():
                    handle.func("final")()
            if len(w2.scene.objs) == 1:
                break
            time.sleep(0.001)
        self.assertEqual(len(w2.scene.objs), 1)
        self.assertEqual(w2.scene.objs[0].transform.x, 4)

    def test_sharing_requires_known_things(self):
        host, guest, hs, gs = self.pair()
        with self.assertRaises(NetError):
            hs.share(object(), "nope")
        with self.assertRaises(NetError):
            hs.share(engine_scene.Scene())
        scene = engine_scene.Scene()
        hs.share(scene, "arena")
        with self.assertRaises(NetError):
            hs.share(engine_scene.Scene(), "arena")
        with self.assertRaises(NetError):
            hs.unshare(engine_scene.Scene())


def frame(origin, target, flags, channel, payload):
    name = channel.encode("utf-8")
    return node_module._HEADER.pack(node_module._DATA, origin, target, flags) + bytes((len(name),)) + name + payload


def wire(sock, data):
    sock.sendall(struct.pack(">I", len(data)) + data)


class HardeningTests(unittest.TestCase):
    def tearDown(self):
        for node in getattr(self, "nodes", []):
            node.close()
        for sock in getattr(self, "socks", []):
            sock.close()

    def star(self, count=2, **kwargs):
        self.nodes = [Node("host", **kwargs)] + [Node("n%d" % i, **kwargs) for i in range(count)]
        self.socks = []
        self.nodes[0].host(0, LOCAL, "tcp")
        for guest in self.nodes[1:]:
            linked(self.nodes[0], guest, "tcp", self.nodes)
        pump(self.nodes, lambda: all(len(n.members) == count for n in self.nodes), timeout=2.0)
        return self.nodes

    def rogue(self, host):
        sock = socket.create_connection((LOCAL, host.listen["tcp"]))
        self.socks.append(sock)
        return sock

    def test_frames_before_handshake_are_never_delivered(self):
        host, a, b = self.star()
        got = []
        host.on("chan", lambda peer, data: got.append(data))
        b.on("chan", lambda peer, data: got.append(data))
        sock = self.rogue(host)
        for target in (0, b.id):
            wire(sock, frame(a.id, target, node_module._RELAY | node_module._RELIABLE, "chan", dumps("forged")))
        wire(sock, bytes((node_module._LEAVE,)) + dumps(a.id))
        wire(sock, bytes((node_module._JOIN,)) + dumps((77, "ghost", None, {})))
        pump(self.nodes, timeout=0.3, condition=lambda: False)
        self.assertEqual(got, [])
        self.assertIn(a.id, host.members)
        self.assertNotIn(77, host.members)

    def test_spoofed_origin_closes_the_offending_link(self):
        host, a, b = self.star()
        got = []
        b.on("chan", lambda peer, data: got.append(data))
        a.peers[host.id].link.send(frame(b.id, 0, node_module._RELAY | node_module._RELIABLE, "chan", dumps(1)))
        self.assertTrue(pump(self.nodes, lambda: a.id not in host.peers))
        self.assertEqual(got, [])
        self.assertIn(b.id, host.peers)

    def test_compression_bomb_is_rejected(self):
        host, a = self.star(1)
        got = []
        host.on("chan", lambda peer, data: got.append(data))
        packer = zlib.compressobj(1)
        zeros = b"\0" * (1 << 20)
        bomb = b"".join(packer.compress(zeros) for _ in range(4 * (MAX_FRAME >> 20))) + packer.flush()
        self.assertLess(len(bomb), 4 << 20)
        a.peers[host.id].link.send(frame(a.id, 0, node_module._RELAY | node_module._RELIABLE | node_module._ZLIB,
                                         "chan", bomb))
        tracemalloc.start()
        try:
            self.assertTrue(pump(self.nodes, lambda: a.id not in host.peers, timeout=10.0))
            peak = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 3 * MAX_FRAME)
        self.assertEqual(got, [])

    def test_bad_payload_from_one_peer_does_not_disconnect_the_rest(self):
        host, a, b = self.star()
        got = []
        b.on("chan", lambda peer, data: got.append(data))
        a.peers[host.id].link.send(frame(a.id, 0, node_module._RELAY | node_module._RELIABLE, "chan", b"\x7f"))
        self.assertTrue(pump(self.nodes, lambda: a.id not in host.peers))
        self.assertEqual(got, [])
        self.assertIn(b.id, host.peers)
        self.assertTrue(b.peers[host.id].direct)
        host.send("chan", "still alive")
        self.assertTrue(pump(self.nodes, lambda: got == ["still alive"]))

    def test_malformed_relayed_payload_is_dropped_not_fatal(self):
        host, a, b = self.star()
        got = []
        b.on("chan", lambda peer, data: got.append(data))
        bad = frame(a.id, 0, node_module._RELAY | node_module._RELIABLE, "chan", b"\x7f")
        host.peers[b.id].link.send(bad)
        host.send("chan", "after")
        self.assertTrue(pump(self.nodes, lambda: got == ["after"]))
        self.assertTrue(b.peers[host.id].direct)

    def test_handler_error_does_not_lose_queued_messages(self):
        host, a = self.star(1)
        got = []

        def handler(peer, data):
            got.append(data)
            if data == 1:
                raise RuntimeError("boom")

        host.on("chan", handler)
        for value in (1, 2, 3):
            a.send("chan", value)
        raised = 0
        end = time.monotonic() + 5
        while len(got) < 3 and time.monotonic() < end:
            a.update()
            try:
                host.update()
            except RuntimeError:
                raised += 1
            time.sleep(0.001)
        self.assertEqual(got, [1, 2, 3])
        self.assertEqual(raised, 1)

    def test_password_is_required_in_both_directions(self):
        host, guest = Node("host"), Node("guest", password="secret")
        self.nodes = [host, guest]
        host.host(0, LOCAL, "tcp")
        stop = threading.Event()
        worker = threading.Thread(target=host.serve, kwargs={"interval": 0.001, "until": stop.is_set})
        worker.start()
        try:
            with self.assertRaises(ConnectError):
                guest.connect((LOCAL, host.listen["tcp"]), "tcp", timeout=1.0)
        finally:
            stop.set()
            worker.join()

    def test_wrong_password_is_rejected_over_udp(self):
        host, guest = Node("host", password="secret"), Node("guest", password="other")
        self.nodes = [host, guest]
        host.host(0, LOCAL, "udp")
        stop = threading.Event()
        worker = threading.Thread(target=host.serve, kwargs={"interval": 0.001, "until": stop.is_set})
        worker.start()
        try:
            with self.assertRaises(ConnectError):
                guest.connect((LOCAL, host.listen["udp"]), "udp", timeout=2.0)
            self.assertEqual(host.peers, {})
        finally:
            stop.set()
            worker.join()

    def test_silent_servers_time_out_without_wait(self):
        listener = TcpListener(LOCAL, 0)
        node = Node("lonely")
        self.nodes = [node]
        link = node.connect((LOCAL, listener.port), "tcp", timeout=0.3, wait=False)
        self.assertTrue(pump([node], lambda: not link.alive, timeout=3.0))
        self.assertEqual(node._links, [])
        listener.close()

    def test_identifiers_are_validated(self):
        for bad in (0, -1, 1 << 32, 1.5, "7"):
            with self.assertRaises(NetError):
                Node("x", ident=bad)
        self.assertEqual(Node("x", ident=7).id, 7)

    def test_unsupported_protocol_is_rejected_before_dialing(self):
        node = Node("x")
        self.nodes = [node]
        with self.assertRaises(NetError):
            node.connect((LOCAL, 1), "sctp")

    def test_tcp_bursts_of_small_and_large_frames_stay_ordered(self):
        listener = TcpListener(LOCAL, 0)
        client = TcpLink.dial((LOCAL, listener.port))
        server = None
        payloads = [bytes([i % 251]) * (i % 97) for i in range(4000)] + [b"x" * 300000, b""]
        for item in payloads:
            client.send(item)
        got = []
        end = time.monotonic() + 10
        while len(got) < len(payloads) and time.monotonic() < end:
            now = time.monotonic()
            client.update(now)
            if server is None:
                found = listener.accept()
                server = found[0] if found else None
            if server is not None:
                server.update(now)
                got += server.recv()
        self.assertEqual(got, payloads)
        client.close()
        server.close()
        listener.close()

    def test_tcp_oversized_frame_header_kills_the_link(self):
        listener = TcpListener(LOCAL, 0)
        sock = socket.create_connection((LOCAL, listener.port))
        sock.sendall(struct.pack(">I", MAX_FRAME + 1))
        server = None
        end = time.monotonic() + 3
        while time.monotonic() < end and (server is None or server.alive):
            found = listener.accept()
            server = found[0] if found and server is None else server
            if server is not None:
                server.update(time.monotonic())
        self.assertFalse(server.alive)
        sock.close()
        listener.close()

    def test_udp_sequence_numbers_survive_32_bit_rollover(self):
        server = UdpEndpoint(LOCAL, 0, accept=True)
        client = UdpEndpoint(LOCAL, 0)
        link = client.connect((LOCAL, server.port))
        theirs = None
        end = time.monotonic() + 5
        while (theirs is None or not link.opened) and time.monotonic() < end:
            now = time.monotonic()
            for fresh in server.update(now):
                theirs = fresh
            client.update(now)
        start = (1 << 32) - 3
        link._next = start
        theirs._expect = start
        link._useq = start
        theirs._ureceived = start
        got = []
        for index in range(8):
            link.send(b"r%d" % index)
            link.send(b"u%d" % index, reliable=False)
        while len(got) < 16 and time.monotonic() < end:
            now = time.monotonic()
            client.update(now)
            server.update(now)
            got += theirs.recv()
        self.assertEqual(sorted(got), sorted([b"r%d" % i for i in range(8)] + [b"u%d" % i for i in range(8)]))
        self.assertTrue(link.alive and theirs.alive)
        server.close()
        client.close()


class HostileSyncTests(unittest.TestCase):
    def setUp(self):
        self.host, self.guest = Node("host"), Node("guest")
        self.nodes = [self.host, self.guest]
        self.host.host(0, LOCAL, "tcp")
        self.hs, self.gs = Sync(self.host), Sync(self.guest)
        self.syncs = [self.hs, self.gs]
        self.a, self.b = engine_scene.Scene(), engine_scene.Scene()
        self.hs.share(self.a, "arena")
        self.gs.share(self.b, "arena")
        self.item = self.a.obj().create("o", 5, 5)
        linked(self.host, self.guest, "tcp", self.syncs)
        pump(self.syncs, lambda: len(self.b.objs) == 1)
        self.replica = self.b.objs[0]

    def tearDown(self):
        for node in self.nodes:
            node.close()

    def inject(self, ops):
        self.guest.send(self.gs.channel, ops)
        pump(self.syncs, timeout=0.3, condition=lambda: False)

    def test_remote_peers_cannot_write_arbitrary_attributes(self):
        entity = self.hs.entity(self.item)
        before_scene = self.item.scene
        self.hs._on_own(self.guest.id, (3, entity.nid, self.guest.id, {}))
        entity.owner = self.guest.id
        for var, value in (("scene", 1), ("_remote", True), ("discard", None), ("__class__", int)):
            self.hs._apply(entity, self.guest.id, {"obj": {var: value}})
        self.assertIs(self.item.scene, before_scene)
        self.assertFalse(self.item._remote)
        self.assertTrue(callable(self.item.discard))
        self.assertIs(type(self.item), engine_scene.obj)

    def test_malformed_operations_are_counted_and_survived(self):
        entity = self.hs.entity(self.item)
        junk = [(1,), (1, 99999), (1, entity.nid, "notadict"), (0,), (2,), (3, entity.nid, "x", 5), (3, 1, None, None),
                [], None, 7, ("a",), (0, 1, 2, 3)]
        self.inject(junk)
        self.assertEqual(self.item.transform.x, 5)
        self.assertTrue(self.host.peers[self.guest.id].direct)

    def test_bad_values_do_not_block_good_ones(self):
        entity = self.hs.entity(self.item)
        entity.owner = self.guest.id
        self.hs._receive(self.guest, [(1, entity.nid, {"transform": {"x": "garbage", "y": 42.0}})])
        self.assertEqual(self.item.transform.y, 42.0)
        self.assertGreaterEqual(self.hs.rejected, 0)

    def test_forged_forward_flag_cannot_create_host_owned_objects(self):
        scene_entity = self.hs.entity(self.a)
        count = len(self.a.objs)
        op = (0, 123456789, scene_entity.nid, "obj", self.host.id, None, {"transform": {"x": 1}}, {}, True)
        self.hs._receive(self.guest, [op])
        self.assertEqual(len(self.a.objs), count)
        self.assertNotIn(123456789, self.hs.entities)

    def test_pending_references_stay_bounded(self):
        entity = self.hs.entity(self.item)
        entity.owner = self.guest.id
        for index in range(500):
            self.hs._receive(self.guest, [(1, entity.nid, {"obj": {"x": Ref(10 ** 9 + index)}})])
        self.assertLessEqual(len(entity.pending), 4)

    def test_unshare_and_close_unfreeze_replicas(self):
        self.assertTrue(self.replica._remote)
        self.gs.unshare(self.b)
        self.assertFalse(self.replica._remote)
        other = Sync(Node("solo"))
        scene = engine_scene.Scene()
        other.share(scene, "x")
        other.entity(scene).layer.remote(scene, True)
        other.close()

    def test_nan_values_do_not_resend_every_frame(self):
        host, guest = Node("h"), Node("g")
        self.nodes += [host, guest]
        host.host(0, LOCAL, "tcp")
        hs, gs = Sync(host), Sync(guest)
        scene, mirror = engine_scene.Scene(), engine_scene.Scene()
        hs.share(scene, "w", vars={"obj": ("hp",)})
        gs.share(mirror, "w", vars={"obj": ("hp",)})
        thing = scene.obj().create("t", 1, 1)
        thing.hp = math.nan
        link = linked(host, guest, "tcp", [hs, gs])
        pump([hs, gs], lambda: len(mirror.objs) == 1)
        pump([hs, gs], timeout=0.2, condition=lambda: False)
        sent = host.peers[guest.id].link.bytes_out
        pump([hs, gs], timeout=0.3, condition=lambda: False)
        self.assertEqual(host.peers[guest.id].link.bytes_out, sent)
        self.assertTrue(math.isnan(mirror.objs[0].hp))


if __name__ == "__main__":
    unittest.main()
