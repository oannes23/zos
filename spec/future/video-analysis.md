# Video Analysis — Future Improvement

**Status**: Designed (not implemented) — deferred to post-MVP
**Purpose**: Extend media analysis to handle video attachments via frame extraction and optional audio transcription

---

## Overview

Extend the existing media analysis pipeline to handle video attachments. Since Anthropic's API has no native video content block, videos are analyzed by extracting key frames via FFmpeg and sending them as a multi-image vision API call. Audio is optionally transcribed via OpenAI Whisper API, with graceful degradation when unavailable.

**Design principle**: If an external dependency (FFmpeg, OpenAI API key) is missing, video analysis degrades gracefully rather than failing. Image analysis continues to work regardless.

---

## Existing Infrastructure (Already Video-Ready)

The codebase already contains several provisions for video:

- `models.py`: `MediaType.VIDEO = "video"` enum exists (currently unused)
- `database.py`: `media_analysis` table has `duration_seconds` column
- `config.py`: `video_duration_threshold_minutes: int = 30` exists
- `spec/domains/observation.md`: Videos < 30 min get frame sampling + analysis; videos >= 30 min get metadata only (TLDW principle)
- Jinja2 templates render `media_descriptions` generically — `[video: clip.mp4] ...` would work with no template changes

---

## Architecture Decisions

### 1. Reuse the existing media queue, dispatch by type

Both images and videos flow through the existing `_media_analysis_queue`. The `_process_media_queue` loop dispatches to `_analyze_image()` or `_analyze_video()` based on a `_is_video()` check. One queue, one consumer, simple routing.

- **Rationale**: Avoids separate queue complexity. Video processing is heavier but the queue is already serial, and media analysis is never time-critical.

### 2. New module: `src/zos/video.py`

Video-specific logic (FFmpeg subprocess calls, frame extraction, audio extraction, Whisper transcription) belongs in a dedicated module. Follows the pattern of `links.py` being separate from `observation.py`.

- **Rationale**: Keeps observation.py from growing further; clean separation of concerns.

### 3. FFmpeg via subprocess, no Python binding library

Use `asyncio.create_subprocess_exec` to call `ffprobe` and `ffmpeg` directly.

- **Rationale**: Avoids heavyweight dependencies like `ffmpeg-python` or `moviepy`. FFmpeg is the most reliable cross-platform tool for this.

### 4. OpenAI Whisper API for audio transcription

Add `openai` as an optional dependency. Transcription degrades gracefully — if the API key is not set or the call fails, analysis proceeds with visual-only description.

- **Rationale**: Mirrors how YouTube transcript handling works in `links.py` (attempt, degrade gracefully). This was an explicit design choice requested during the planning session.

---

## Files to Modify

| File | Changes |
|---|---|
| `src/zos/config.py` | Add video config fields to `ObservationConfig` |
| `src/zos/video.py` | **New file** — FFmpeg probing, frame extraction, audio extraction, Whisper transcription, orchestration |
| `src/zos/llm.py` | Add `analyze_video_frames()` method for multi-image vision calls |
| `src/zos/observation.py` | Add `_is_video()`, `SUPPORTED_VIDEO_TYPES`, modify queue to accept videos, add `_analyze_video()` dispatch |
| `tests/test_video.py` | **New file** — Comprehensive tests with mocked subprocess/API calls |
| `pyproject.toml` | Add `openai` to optional `[video]` dependency group |

---

## Implementation Details

### Configuration (`src/zos/config.py`)

New fields in `ObservationConfig`:

| Field | Type | Default | Purpose |
|---|---|---|---|
| `video_analysis_enabled` | bool | True | Master toggle for video processing (separate from `vision_enabled` because video requires FFmpeg) |
| `video_max_frames` | int | 8 | Maximum frames to extract per video |
| `video_max_download_mb` | int | 100 | Maximum video file size to download |
| `video_audio_transcription_enabled` | bool | True | Toggle for Whisper audio transcription |
| `video_audio_max_duration_seconds` | int | 300 | Maximum audio length to transcribe (5 min) |

Existing fields reused as-is:
- `vision_enabled` (master switch for all media vision)
- `video_duration_threshold_minutes: int = 30` (already exists)
- `vision_rate_limit_per_minute` (shared rate limiter)

### Video Module (`src/zos/video.py`)

Key functions:

- `check_ffmpeg_available()` — runs `ffmpeg -version` to verify installation
- `probe_video(path) -> VideoMetadata` — calls `ffprobe -print_format json` to get duration, resolution, has_audio
- `extract_frames(path, output_dir, max_frames, duration) -> list[Path]` — evenly-spaced frame extraction via `ffmpeg -ss {t} -i {input} -frames:v 1 -q:v 2 {output.jpg}`
- `extract_audio(path, output_path, max_duration) -> Path | None` — extracts audio track as MP3 via `ffmpeg -vn -acodec libmp3lame`
- `transcribe_audio(path, config) -> str | None` — calls OpenAI Whisper API; gracefully returns None on any failure
- `analyze_video(video_data, filename, config, llm) -> VideoAnalysisResult` — orchestrates the full pipeline

Key dataclasses:

```python
@dataclass
class VideoMetadata:
    duration_seconds: float
    width: int
    height: int
    codec: str | None = None
    has_audio: bool = False

@dataclass
class VideoAnalysisResult:
    description: str
    duration_seconds: int
    width: int
    height: int
    analysis_model: str | None = None
    frame_count: int = 0
    has_transcript: bool = False
```

**Frame extraction strategy**: Divide video duration by `max_frames`, extract one frame at each evenly-spaced interval. Short videos (< 3s) get 3 frames (start/middle/end). Videos < 10s get min(N, 4) frames.

### Vision Prompt

```
You are looking at {frame_count} frames extracted from a video that is {duration} seconds long.
The frames are evenly spaced throughout the video to capture its progression.

{audio_context}

Describe this video as if recounting it to someone who hasn't seen it.

Focus on:
- What the video appears to show (action, scene, subject)
- How the content progresses or changes across frames
- The overall mood, tone, or atmosphere
- Any text, captions, or symbols visible
- What this video might mean in a social/conversational context (clip, meme, tutorial, reaction, etc.)

Write 3-5 sentences capturing both what you see happening and what it feels like to watch it.
```

Metadata-only template (for videos exceeding the duration threshold):

```
Video attachment: {filename} ({duration_str}, {resolution}).
Too long for frame analysis (>{threshold} min threshold).
Content not analyzed.
```

### Multi-Image Vision (`src/zos/llm.py`)

Add `analyze_video_frames()` method that:
- Accepts `list[tuple[str, str]]` of `(base64_data, mime_type)` frames
- Constructs a message with N `{"type": "image", ...}` content blocks + 1 `{"type": "text", ...}` block
- Uses `max_tokens=2048` (higher than single-image's 1024)
- Follows existing patterns: rate limiting, call recording, provider dispatch

### Audio Transcription (Graceful Degradation)

The Whisper integration checks at every stage and returns `None` (proceeding with visual-only) if:
- `video_audio_transcription_enabled` is False
- `openai` package is not installed
- `OPENAI_API_KEY` environment variable is not set
- The Whisper API call fails for any reason
- The transcript is empty

### Observation Integration (`src/zos/observation.py`)

```python
SUPPORTED_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime", "video/x-msvideo", "video/x-matroska"}
```

- `_is_video()` checks `attachment.content_type` with fallback to extension (`.mp4`, `.webm`, `.mov`, `.avi`, `.mkv`)
- `_queue_media_for_analysis()` adds `or self._is_video(attachment)` to existing image check, enforcing `video_max_download_mb`
- `_process_media_queue()` dispatches to `_analyze_video()` or `_analyze_image()` based on type
- `_analyze_video()` lazily imports from `zos.video`, checks FFmpeg, downloads, analyzes, stores `MediaAnalysis` with `MediaType.VIDEO`

---

## Error Handling

| Condition | Behavior |
|---|---|
| FFmpeg not installed | Log warning, skip all video analysis, images still work |
| Video too large | Skip at queue time, log info with file size |
| Video download fails | Catch exception, log warning, continue processing queue |
| ffprobe fails | Log warning, skip this video |
| Frame extraction fails | Log warning, skip this video |
| Audio extraction fails | Proceed with visual-only description |
| openai not installed / no API key | Proceed with visual-only description |
| Whisper API call fails | Log warning, proceed with visual-only description |
| Vision API fails on frames | Log warning, skip this video |
| Video exceeds duration threshold | Return metadata-only description, no API calls |
| Temp file cleanup fails | Log warning, continue (non-fatal) |

---

## Dependencies

```toml
[project.optional-dependencies]
video = ["openai>=1.0.0"]
```

**System dependency**: FFmpeg must be installed on the host. Not declared in pyproject.toml.

---

## Testing Strategy

Comprehensive tests in `tests/test_video.py` with all externals mocked:

- `TestVideoDetection` — MIME type and filename extension detection
- `TestVideoMetadata` — ffprobe subprocess mock
- `TestFrameExtraction` — ffmpeg subprocess mock
- `TestAudioExtraction` — ffmpeg audio extraction mock
- `TestWhisperTranscription` — openai import/API mock, graceful degradation paths
- `TestVideoAnalysisPipeline` — full pipeline with all externals mocked
- `TestVideoQueueing` — observation queue routing for videos vs images
- `TestVideoConfig` — configuration field defaults and custom values

Mock strategies: `asyncio.create_subprocess_exec` is mocked to simulate ffprobe/ffmpeg output without requiring actual binaries. `openai.AsyncOpenAI` is mocked for Whisper API tests. No real video files needed.

---

## Verification Plan

1. **Unit tests**: `pytest tests/test_video.py` — all subprocess and API calls mocked
2. **Integration smoke test** (requires FFmpeg installed):
   - Post a short MP4 video in a Discord channel Zos monitors
   - Check logs for `video_analysis_start` and `video_analyzed` events
   - Query media analysis API to see video analysis record
   - Trigger a reflection and verify the video description appears in context
3. **Graceful degradation test**:
   - Unset `OPENAI_API_KEY` — verify video analysis still completes (visual-only)
   - Set `video_analysis_enabled: false` — verify videos are not queued

---

## Implementation Order

1. **Config** — add new fields to `ObservationConfig` (no dependencies)
2. **video.py** — create the new module with FFmpeg/Whisper logic
3. **llm.py** — add `analyze_video_frames()` for multi-image vision calls
4. **observation.py** — add detection, queueing, and dispatch logic
5. **tests/test_video.py** — tests for all new code
6. **pyproject.toml** — add optional openai dependency

Steps 1-3 are largely independent. Step 4 depends on 1-3. Step 5 follows step 4.

---

## Key Constraints

- Anthropic's API does **not** support native video content blocks — frame extraction is required
- Anthropic supports up to 100 images per request; this design sends 3-8 frames
- No video processing library currently exists in the project's dependencies
- FFmpeg is a system dependency that may not be present on all hosts

---

## Relationship to Other Specs

| Spec | Relevance |
|------|-----------|
| [observation.md](../domains/observation.md) | Video analysis extends the existing media observation pipeline |
| [layers.md](../domains/layers.md) | Video descriptions flow through the same layer system as images |

---

_This is a future improvement document. It captures a complete design ready for implementation when prioritized._

---

**Source**: Designed in planning session with Claude Opus 4.5, January 2026.

_Created: 2026-01-30_
