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

**Note:** `./run.sh` automatically isolates the OpenCode database if a v1/v2 version conflict is detected (`Database is not empty and has no session table`). The isolated DB is stored alongside the global one and leaves the original untouched. Run `make doctor` to see the current state.

Full instructions: [README.md](README.md)
