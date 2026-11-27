import os, pathlib, shutil, subprocess, sys, tempfile

case = pathlib.Path(os.environ["CASE_DIR"])
with tempfile.TemporaryDirectory() as tmp:
    shutil.copy("owners.py", tmp)
    shutil.copy(case / "checks/pristine_test_owners.py", pathlib.Path(tmp) / "test_pristine.py")
    failed = []
    for seed in range(30):
        env = {**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONDONTWRITEBYTECODE": "1"}
        done = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_pristine"], cwd=tmp, env=env,
                              capture_output=True, text=True)
        if done.returncode != 0:
            failed.append(seed)
    print(f"pristine test failed under {len(failed)} of 30 hash seeds: {failed}")
    sys.exit(1 if failed else 0)
