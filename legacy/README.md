# Earlier MusicCraft prototype

`musiccraft-v02/` preserves the original Python application, proposal and demo documents from commit `3406925` before the current Node-based MusicCraft application was added at the repository root.

Use the repository-root README and `.env.example` for the current implementation. Legacy statements about unconfigured services describe the earlier prototype. Its standalone public demo uses synthetic placeholder audio and is not the real GPU-backed service.

To run the earlier application separately:

```bash
cd legacy/musiccraft-v02
python3 -B run.py
```

Legacy GPU scripts and environment variable names are retained for history; use the current `deploy/` and `docs/VOICE_AND_MODELS.md` for the verified voice pipeline.
