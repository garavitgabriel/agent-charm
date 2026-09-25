"""End-to-end check of the live sim against the real charm server, with no network and no Hermes.

The real server (`charm_server.server.start`) runs in-process with the server's own test fakes for
STT, Dex and TTS, *imported* from `server/tests/conftest.py` (nothing in server/ is edited). The sim
connects headlessly, holds the talk button once and speaks `sim/tests/fixtures/question.wav` into
it. The check passes when the answer card is on the sim's screen, its `displayed` receipt went back,
and every byte of the fake speech reached the sim's speaker.

    uv run --project server python scripts/integration_test.py --sim build/sim/charm-sim

ctest runs it as `sim_live_integration`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))  # makes server/tests importable as `tests`

from charm_server.cards import CardValidator  # noqa: E402
from charm_server.config import Config  # noqa: E402
from charm_server.server import start  # noqa: E402
from charm_server.session import Deps  # noqa: E402
from tests.conftest import FakeAgent, FakeSTT, FakeTTS  # noqa: E402

TOKEN = "integration-token"
WAV = REPO / "sim" / "tests" / "fixtures" / "question.wav"
SCHEMA = REPO / "contract" / "card.schema.json"


class Failed(Exception):
    pass


def check(ok: bool, what: str) -> None:
    print(("  ok    " if ok else "  FAIL  ") + what)
    if not ok:
        raise Failed(what)


async def run_sim(sim: str, url: str, token: str, *extra: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        sim,
        "--connect",
        url,
        "--headless",
        "--trace",
        *extra,
        env={**os.environ, "CHARM_TOKEN": token},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(proc.communicate(), timeout=90)
    return proc.returncode or 0, out.decode(), err.decode()


async def wait_for_line(stream: asyncio.StreamReader, needle: str, seconds: float) -> None:
    async with asyncio.timeout(seconds):
        while True:
            line = (await stream.readline()).decode()
            if not line:
                raise Failed(f"the sim exited before printing {needle!r}")
            sys.stderr.write(line)
            if needle in line:
                return


async def reconnect(sim: str, deps: Deps, port: int) -> None:
    """The server goes away and comes back on the same port: the sim goes offline, then back."""
    server = await start(deps, "127.0.0.1", port)
    proc = await asyncio.create_subprocess_exec(
        sim,
        "--connect",
        f"ws://127.0.0.1:{port}/charm",
        "--headless",
        "--timeout",
        "20000",
        env={**os.environ, "CHARM_TOKEN": TOKEN},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stderr is not None
    try:
        await wait_for_line(proc.stderr, "welcome: online", 5)
        server.close()
        await server.wait_closed()
        await wait_for_line(proc.stderr, "[net] down", 5)
        check(True, "the sim noticed the server going away")
        server = await start(deps, "127.0.0.1", port)
        await wait_for_line(proc.stderr, "welcome: online", 10)
        check(True, "the sim reconnected with backoff and was welcomed again")
    except TimeoutError:
        check(False, "the sim reconnected in time")
    finally:
        proc.terminate()
        await proc.wait()
        server.close()
        await server.wait_closed()


async def main(sim: str) -> int:
    stt, agent, tts = FakeSTT(), FakeAgent(), FakeTTS()
    with tempfile.TemporaryDirectory() as tmp:
        config = Config(
            token=TOKEN,
            host="127.0.0.1",
            port=0,
            hermes_ssh_alias="unused",
            hermes_container="unused",
            cards_dir=REPO / "contract" / "examples",
            schema_path=SCHEMA,
            action_log=Path(tmp) / "actions.jsonl",
            tz="America/Chicago",
            voice_en="en-voice",
            voice_es="es-voice",
            whisper_model="unused",
        )
        deps = Deps(
            config=config,
            stt=stt,
            agent=agent,
            tts=tts,
            validator=CardValidator(SCHEMA),
            speech_lead_s=None,
        )
        server = await start(deps, "127.0.0.1", 0)
        port = next(iter(server.sockets)).getsockname()[1]
        url = f"ws://127.0.0.1:{port}/charm"
        try:
            print(f"talk round trip: {sim} -> {url}")
            code, out, err = await run_sim(
                sim, url, TOKEN, "--mic-wav", str(WAV), "--auto-talk", "--timeout", "30000"
            )
            sys.stderr.write(err)
            result = re.search(
                r"\[result\] answer=(\S*) on_screen=(\S*) surface=(\S*) speech_bytes=(\d+)", err
            )
            check(code == 0, f"the sim finished the reply (exit {code})")
            check("[net] welcome: online" in err, "hello/welcome over the real socket")
            check(stt.calls == 1, "the server transcribed one talk from the WAV")
            check(len(agent.calls) == 1, "Dex (fake) was asked once")
            check(len(tts.calls) >= 1, "speech was synthesized")
            check(result is not None, "the sim reported its screen")
            assert result is not None
            answer, on_screen, surface, speech = result.groups()
            check(answer != "", f"an answer card arrived ({answer})")
            check(on_screen == answer, f"the answer card is on screen (surface {surface})")
            receipts = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
            check(
                {"type": "displayed", "id": answer} in receipts,
                "the sim sent displayed{id} for the answer",
            )
            check(
                int(speech) == len(tts.pcm),
                f"all speech reached the speaker ({speech} of {len(tts.pcm)} bytes)",
            )

            print("wrong token")
            code, out, err = await run_sim(sim, url, "not-the-token", "--timeout", "2500")
            check("refused our token" in err, "the server's auth error reached the sim")
            check("welcome: online" not in err, "the sim never went online")
        except Failed:
            return 1
        finally:
            server.close()
            await server.wait_closed()
        try:
            print("server restart")
            await reconnect(sim, deps, port)
        except Failed:
            return 1
    print("sim_live_integration: pass")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sim", required=True, help="path to the charm-sim binary")
    sys.exit(asyncio.run(main(parser.parse_args().sim)))
