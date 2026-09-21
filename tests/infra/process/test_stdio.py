import sys
import asyncio
import socket

import pytest

from tinysoul.infra.process import ManagedProcessRequest, StdioProcess


async def test_protocol_pipe_round_trip_and_idempotent_tree_close() -> None:
    process = await StdioProcess.start(
        ManagedProcessRequest(
            (
                sys.executable,
                "-u",
                "-c",
                "import sys; print(sys.stdin.readline().strip(), flush=True); sys.stdin.read()",
            ),
        )
    )
    try:
        process.stdin.write(b"hello\n")
        await process.stdin.drain()
        assert (await process.stdout.readline()).strip() == b"hello"
    finally:
        await process.close()
    assert await process.close() == ()


@pytest.mark.parametrize("root_exits", [False, True])
async def test_protocol_close_reaps_descendant_after_root_exit(
    root_exits: bool,
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(8)
        child = (
            "import socket; "
            f"s=socket.create_connection({listener.getsockname()!r}); "
            "s.sendall(b'ready'); s.recv(1)"
        )
        parent = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-c',{child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
            + ("print('root_exit',flush=True)" if root_exits else "time.sleep(30)")
        )
        process = await StdioProcess.start(
            ManagedProcessRequest((sys.executable, "-u", "-c", parent))
        )
        try:
            peer, _ = await asyncio.to_thread(listener.accept)
            with peer:
                peer.settimeout(5)
                assert await asyncio.to_thread(peer.recv, 5) == b"ready"
                if root_exits:
                    assert (await process.stdout.readline()).strip() == b"root_exit"
                    assert await process.stdout.read() == b""
                await process.close()
                try:
                    assert await asyncio.to_thread(peer.recv, 1) == b""
                except ConnectionResetError:
                    pass
        finally:
            await process.close()
