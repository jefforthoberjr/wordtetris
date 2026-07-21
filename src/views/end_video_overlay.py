import pyglet
from pyglet.media.codecs.ffmpeg import FFmpegDecoder


class EndVideoOverlay:
    """A one-shot fullscreen video played when the game freezes (game_screen.end_video).

    Owns TWO pyglet media Players started together (see play()): one decodes the
    VIDEO (FFmpeg, driven by the wall-clock timer, drawn fullscreen), the other the
    AUDIO (platform-native decoder). They are split because each half of the file
    needs a different decoder on this stack -- see the play() notes and TECH.md
    ("Sound / audio"). draw() blits the current video frame; update() tears both
    down once the video plays through. A silent no-op when no clip is configured
    (path is None), so every mode that leaves the rule unset is unaffected.
    """

    def __init__(self, window, path):
        self._window = window
        self._path = path  # None => feature off
        self._player = None        # video
        self._audio_player = None  # soundtrack (see play())
        self._duration = 0.0

    @property
    def name(self):
        """The clip's filename (for logging), or "" when the feature is off."""
        return self._path.name if self._path is not None else ""

    @property
    def active(self):
        """True while a clip is on screen -- between play() and its on_eos teardown.
        draw() and the caller gate on this."""
        return self._player is not None

    def play(self):
        """Start the clip from the top. A fresh source is loaded each call because a
        pyglet source is consumed once played -- so this also covers a replayed game
        within the same screen. No-op when the feature is off (path None)."""
        if self._path is None:
            return
        self.stop()
        # VIDEO: force the FFmpeg decoder -- the platform decoders return audio only
        # (video_format None, no frames) for .mp4. Its audio track is DROPPED
        # (audio_format = None) because pyglet 2.1.14's FFmpeg *audio* decode yields
        # zero bytes against FFmpeg 8.x, which the audio player reads as instant
        # end-of-stream and tears the whole clip down after one black frame (the
        # original "1 frame of black" bug -- see ONGOING_BUGS.md / TECH.md). With no
        # audio track the video runs on the wall-clock timer and plays through.
        source = pyglet.media.load(str(self._path), decoder=FFmpegDecoder())
        source.audio_format = None
        self._duration = source.duration
        self._player = pyglet.media.Player()
        self._player.queue(source)
        self._player.play()
        # AUDIO: play the SAME file's soundtrack through the platform-native decoder
        # (macOS CoreAudio / Windows WMF -- NOT FFmpeg, whose audio path is the broken
        # one above), started right alongside the video so the two stay in sync over
        # the clip. Best-effort: any load/play failure (or a file with no audio) just
        # leaves the clip silent rather than breaking the end screen.
        try:
            audio_source = pyglet.media.load(str(self._path))   # default decoder
            if audio_source.audio_format is not None:
                self._audio_player = pyglet.media.Player()
                self._audio_player.queue(audio_source)
                self._audio_player.play()
        except Exception:
            self._audio_player = None

    def update(self):
        """Tear the clip down once it has played through. Two end signals, either
        of which triggers teardown: (a) the play time reaches the source duration;
        (b) the Player's source goes None -- the video-only path (audio disabled in
        play()) dispatches on_eos when its frames run out, which drops the source and
        resets the clock to 0, so a pure time>=duration poll would miss it. Call once
        per frame; a no-op while nothing is playing."""
        if self._player is None:
            return
        if self._player.source is None or self._player.time >= self._duration:
            self.stop()

    def stop(self):
        """Tear down BOTH players -- the clip ended, or the game screen is leaving (so
        the audio does not keep playing off-screen). Safe to call when idle."""
        if self._player is not None:
            self._player.pause()
            self._player.delete()
            self._player = None
        if self._audio_player is not None:
            self._audio_player.pause()
            self._audio_player.delete()
            self._audio_player = None

    def draw(self):
        """Blit the current video frame stretched to fill the whole window. Nothing
        before play() or after the clip ends; the texture can be None between frames
        early on, so guard it."""
        if self._player is None:
            return
        texture = self._player.texture
        if texture is None:
            return
        texture.blit(0, 0, width=self._window.width, height=self._window.height)
