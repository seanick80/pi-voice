"""OVOS Timer Skill — voice-controlled kitchen timers with Good Morning dashboard integration."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import requests
from ovos_bus_client import Message
from ovos_utils import classproperty
from ovos_utils.log import LOG
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.decorators import intent_handler
from ovos_workshop.skills import OVOSSkill

# Good Morning API running on the same Pi
GM_API = "http://localhost:8000/api"


_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "forty five": 45, "forty-five": 45, "fifty": 50, "sixty": 60,
    "ninety": 90, "a": 1, "an": 1,
}


def _to_num(s: str) -> int | None:
    """Convert a digit string or word number to int."""
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    return _WORD_TO_NUM.get(s)


def _parse_duration(message) -> int | None:
    """Extract duration in seconds from an utterance message.

    Handles patterns like:
      "set a timer for 5 minutes"
      "set a 10 minute timer for pasta"
      "set a 30 second timer"
      "set a timer for 1 hour and 30 minutes"
      "set a timer for one minute"
      "set a timer for a minute and a half"
    """
    text = message.data.get("utterance", "").lower()
    seconds = 0
    found = False

    import re

    word_nums = "|".join(k for k in _WORD_TO_NUM if " " not in k and "-" not in k)
    num_pat = rf"(\d+|{word_nums})"

    # Match patterns like "5 minutes", "one hour", "30 seconds"
    for match in re.finditer(
        num_pat + r"\s*(hours?|minutes?|mins?|seconds?|secs?)",
        text,
    ):
        num = _to_num(match.group(1))
        if num is None:
            continue
        unit = match.group(2)
        if unit.startswith("hour"):
            seconds += num * 3600
        elif unit.startswith("min"):
            seconds += num * 60
        elif unit.startswith("sec"):
            seconds += num
        found = True

    # "half" after minutes → add 30 seconds
    if found and re.search(r"and a half", text):
        seconds += 30

    # Bare number — assume minutes (e.g., "set a timer for 5")
    if not found:
        m = re.search(r"(\d+)", text)
        if m:
            seconds = int(m.group(1)) * 60
            found = True

    return seconds if found and seconds > 0 else None


def _parse_label(message) -> str:
    """Extract optional label from utterance (word after 'for' at end)."""
    text = message.data.get("utterance", "").lower()
    import re

    # "set a 5 minute timer for pasta" → "pasta"
    # "set a timer for 5 minutes for eggs" → "eggs"
    # But NOT "set a timer for 5 minutes" (duration, not label)
    m = re.search(
        r"\bfor\s+(?!\d)([a-z ]+?)(?:\s+timer)?$",
        text.strip(),
    )
    return m.group(1).strip() if m else ""


class TimerSkill(OVOSSkill):
    """Kitchen timer skill that integrates with the Good Morning dashboard."""

    # Alarm sound — electronic alarm clock tone
    _alarm_sound = (
        "/opt/pi-voice/alarm.mp3"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._alarm_threads: dict[int, threading.Event] = {}
        self._alarm_lock = threading.Lock()
        self._duck_event = threading.Event()
        self._unduck_timer: threading.Timer | None = None

    @classproperty
    def runtime_requirements(self):
        # No network/internet required — API is on localhost
        return RuntimeRequirements(
            internet_before_load=False,
            network_before_load=False,
            gui_before_load=False,
            requires_internet=False,
            requires_network=False,
            requires_gui=False,
            no_internet_fallback=True,
            no_network_fallback=True,
            no_gui_fallback=True,
        )

    def initialize(self):
        # Poll for ringing timers every 5 seconds
        self.schedule_repeating_event(
            self._check_ringing, None, 5, name="timer_check",
        )
        # Duck alarm when wake word detected so mic can hear the command
        self.bus.on("recognizer_loop:wakeword", self._on_wakeword)
        self._alarm_ducked = False

    def _on_wakeword(self, message=None):
        """Temporarily pause alarm sounds when wake word is heard."""
        if not self._alarm_threads:
            return
        LOG.info("Timer alarm ducked for wakeword")
        self._alarm_ducked = True
        # Interrupt any in-progress wait so the thread sees ducked=True now
        self._duck_event.set()
        # Resume after 10s if not dismissed
        if self._unduck_timer:
            self._unduck_timer.cancel()
        self._unduck_timer = threading.Timer(10.0, self._unduck_alarm)
        self._unduck_timer.start()

    def _unduck_alarm(self):
        LOG.info("Timer alarm un-ducked")
        self._alarm_ducked = False
        self._duck_event.clear()

    # ── Intent handlers ──────────────────────────────────────────────

    @intent_handler("SetTimer.intent")
    def handle_set_timer(self, message):
        duration = _parse_duration(message)
        if not duration:
            self.speak("I didn't catch the duration. "
                       "Try saying something like: set a timer for 5 minutes.")
            return

        label = _parse_label(message)

        try:
            resp = requests.post(
                f"{GM_API}/timers/",
                json={"duration_seconds": duration, "label": label},
                timeout=5,
            )
        except requests.RequestException:
            LOG.exception("Failed to create timer via API")
            self.speak("Sorry, I couldn't reach the dashboard to set the timer.")
            return

        if resp.status_code == 409:
            self.speak("You already have two timers running. "
                       "Cancel one first.")
            return
        if resp.status_code != 201:
            LOG.error("Timer API returned %s: %s", resp.status_code, resp.text)
            self.speak("Something went wrong setting the timer.")
            return

        data = resp.json()
        name = label or "Timer"
        mins = duration // 60
        secs = duration % 60
        if mins and secs:
            self.speak(f"{name} set for {mins} minutes and {secs} seconds.")
        elif mins:
            unit = "minute" if mins == 1 else "minutes"
            self.speak(f"{name} set for {mins} {unit}.")
        else:
            unit = "second" if secs == 1 else "seconds"
            self.speak(f"{name} set for {secs} {unit}.")

        # Schedule a callback for when this timer should ring
        self.schedule_event(
            self._timer_expired,
            datetime.fromisoformat(data["expires_at"]),
            data={"timer_id": data["id"], "label": label},
            name=f"timer_{data['id']}",
        )

    @intent_handler("TimerStatus.intent")
    def handle_timer_status(self, message):
        timers = self._get_active_timers()
        if not timers:
            self.speak("No timers are running.")
            return

        now = datetime.now(tz=timezone.utc)
        parts = []
        for t in timers:
            expires = datetime.fromisoformat(t["expires_at"])
            remaining = max(0, int((expires - now).total_seconds()))
            name = t["label"] or "Timer"
            if t["status"] == "ringing":
                parts.append(f"{name} is done")
            else:
                mins = remaining // 60
                secs = remaining % 60
                if mins:
                    parts.append(f"{name}: {mins} minutes left")
                else:
                    parts.append(f"{name}: {secs} seconds left")

        self.speak(". ".join(parts) + ".")

    @intent_handler("CancelTimer.intent")
    def handle_cancel_timer(self, message):
        timers = self._get_active_timers()
        if not timers:
            self.speak("There are no active timers.")
            return

        text = message.data.get("utterance", "").lower()

        # "cancel all timers" — cancel everything
        if "all" in text:
            for t in timers:
                try:
                    requests.delete(f"{GM_API}/timers/{t['id']}/", timeout=5)
                except requests.RequestException:
                    pass
                self._stop_alarm(t["id"])
            count = len(timers)
            unit = "timer" if count == 1 else "timers"
            self.speak(f"Cancelled {count} {unit}.")
            return

        # If only one, cancel it. If two, try to match by label.
        target = None
        if len(timers) == 1:
            target = timers[0]
        else:
            for t in timers:
                if t["label"] and t["label"].lower() in text:
                    target = t
                    break
            if not target:
                target = timers[0]

        try:
            requests.delete(f"{GM_API}/timers/{target['id']}/", timeout=5)
        except requests.RequestException:
            self.speak("Sorry, I couldn't cancel the timer.")
            return

        self._stop_alarm(target["id"])
        name = target["label"] or "Timer"
        self.speak(f"{name} cancelled.")

    @intent_handler("StopTimer.intent")
    def handle_stop_timer(self, message):
        """Dismiss ringing timers (stop the alarm)."""
        had_alarms = bool(self._alarm_threads)
        ringing = [
            t for t in self._get_active_timers() if t["status"] == "ringing"
        ]
        if not ringing and not had_alarms:
            # Nothing ringing — maybe they mean cancel
            return self.handle_cancel_timer(message)

        try:
            requests.post(f"{GM_API}/timers/dismiss/", timeout=5)
        except requests.RequestException:
            LOG.warning("Could not reach dismiss API")

        # Hard-stop all local alarm threads
        self._stop_all_alarms()
        self.speak("Timer dismissed.")

    def stop(self) -> bool:
        """Handle global 'stop' command — dismiss ringing timers.

        Always kills local alarm threads even if API call fails,
        so the sound stops regardless.
        """
        had_alarms = bool(self._alarm_threads)
        # Try to dismiss in the backend (best-effort)
        try:
            requests.post(f"{GM_API}/timers/dismiss/", timeout=5)
        except requests.RequestException:
            LOG.warning("Could not reach dismiss API")
        # Hard-stop all local alarm threads unconditionally
        self._stop_all_alarms()
        return had_alarms

    # ── Timer expiry & alarm ─────────────────────────────────────────

    def _timer_expired(self, message):
        """Called when a scheduled timer reaches its expiry time."""
        timer_id = message.data.get("timer_id")
        label = message.data.get("label", "")
        name = label or "Your timer"
        LOG.info("Timer %s (%s) expired", timer_id, name)

        # Announce via TTS
        self.speak(f"{name} is done!")

        # Start repeating alarm sound
        self._start_alarm(timer_id)

    def _start_alarm(self, timer_id: int) -> None:
        """Play repeating alarm tone until dismissed. Idempotent."""
        with self._alarm_lock:
            if timer_id in self._alarm_threads:
                return  # Already ringing — don't spawn a second thread
            stop_event = threading.Event()
            self._alarm_threads[timer_id] = stop_event

        def _play() -> None:
            self.bus.emit(Message(
                "mycroft.audio.play_sound",
                {"uri": self._alarm_sound},
            ))

        def _ring() -> None:
            while not stop_event.is_set():
                if not self._alarm_ducked:
                    _play()
                    # Wait for sound (~8s) plus pause, but wake up
                    # early if ducked or stopped
                    for _ in range(24):  # 24 × 0.5s = 12s max
                        if stop_event.is_set() or self._duck_event.is_set():
                            break
                        stop_event.wait(0.5)
                else:
                    # While ducked, check frequently for un-duck or stop
                    stop_event.wait(0.5)

        t = threading.Thread(target=_ring, daemon=True)
        t.start()

    def _stop_alarm(self, timer_id: int) -> None:
        """Stop the repeating alarm for a timer."""
        with self._alarm_lock:
            stop_event = self._alarm_threads.pop(timer_id, None)
        if stop_event:
            stop_event.set()

    def _stop_all_alarms(self) -> None:
        """Hard-stop every active alarm thread."""
        with self._alarm_lock:
            events = list(self._alarm_threads.values())
            self._alarm_threads.clear()
        for ev in events:
            ev.set()

    def _check_ringing(self, message=None) -> None:
        """Periodic check: start alarms for newly ringing timers,
        stop alarms for timers dismissed via dashboard."""
        active = self._get_active_timers()
        ringing_ids = {t["id"] for t in active if t["status"] == "ringing"}

        # Start alarms for newly ringing timers
        for t in active:
            if t["status"] == "ringing" and t["id"] not in self._alarm_threads:
                label = t["label"] or "Your timer"
                self.speak(f"{label} is done!")
                self._start_alarm(t["id"])

        # Stop alarms for timers that were dismissed externally (e.g. dashboard)
        with self._alarm_lock:
            orphaned = [
                tid for tid in self._alarm_threads if tid not in ringing_ids
            ]
        for tid in orphaned:
            self._stop_alarm(tid)

    # ── API helpers ──────────────────────────────────────────────────

    def _get_active_timers(self) -> list[dict]:
        try:
            resp = requests.get(f"{GM_API}/timers/", timeout=5)
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            LOG.warning("Could not reach timer API")
        return []
