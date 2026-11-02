# Job Hunter in 5 minutes

From a fork or a downloaded ZIP:

```bash
./setup.sh && ./run.sh
```

Or, step by step:

```bash
cd job-hunter
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bun install
./run.sh
```

Then, inside OpenCode:

```
/setup
/profile-build
/find-jobs
```

Your first report is in `reports/<persona>/` (timestamped in Cairo time, grouped by day).

**Note:** Job Hunter uses its own per-major OpenCode databases (`~/.local/share/job-hunter/v1/` and `v2/`). The global `opencode.db` is never read or modified. Run `make doctor` to see the current state.

Full instructions: [README.md](README.md)
