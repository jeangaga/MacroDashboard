"""Run every suite in tests/ offline and print one pass/fail summary.

    py run_tests.py              # all suites   (use `python` where it's on PATH)
    py run_tests.py -k catalogue # only suites whose name matches
    py run_tests.py -v           # stream each suite's full output
    py run_tests.py --real-streamlit   # use the installed streamlit

Each suite is a standalone script that prints a trailing "N ok, M fail" line
and exits non-zero on failure, so they are run as subprocesses (isolated
module state, and a suite calling sys.exit() can't take the runner with it).

Two environment problems are handled here so the suites don't have to care:

1. Old / missing streamlit. The suites that import `streamlit_app` need
   `st.cache_data`, `st.rerun` and row-selection `st.dataframe`. Rather than
   require a modern streamlit locally, `tests/_stubs` is prepended to
   PYTHONPATH so `import streamlit` resolves to the offline stub. Pass
   --real-streamlit to test against the installed package instead.

2. Conda's unimportable ssl. On Windows, anaconda's OpenSSL DLLs live in
   Library\\bin, which is only on PATH inside an activated conda shell. Without
   it `import ssl` fails, which breaks `requests` and therefore
   `utils.github`. If ssl is broken and this looks like a conda layout, the
   relevant directories are prepended to PATH for the subprocesses.

Nothing here is imported by the app; it exists purely for local verification
before hand-uploading changes to GitHub.
"""
from __future__ import print_function

import argparse
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
TESTS_DIR = os.path.join(REPO_ROOT, "tests")
STUBS_DIR = os.path.join(TESTS_DIR, "_stubs")

_RESULT_RE = re.compile(r"(\d+)\s+ok,\s+(\d+)\s+fail")


def discover(pattern=None):
    if not os.path.isdir(TESTS_DIR):
        return []
    names = sorted(n for n in os.listdir(TESTS_DIR)
                   if n.startswith("test_") and n.endswith(".py"))
    if pattern:
        names = [n for n in names if pattern.lower() in n.lower()]
    return [os.path.join(TESTS_DIR, n) for n in names]


def _ssl_is_broken():
    try:
        import ssl  # noqa: F401
        return False
    except Exception:
        return True


def _conda_dll_dirs():
    """Directories a conda install needs on PATH for ssl to import."""
    prefix = sys.prefix
    candidates = [
        prefix,
        os.path.join(prefix, "Library", "bin"),
        os.path.join(prefix, "Library", "mingw-w64", "bin"),
        os.path.join(prefix, "Library", "usr", "bin"),
        os.path.join(prefix, "Scripts"),
    ]
    return [d for d in candidates if os.path.isdir(d)]


def build_env(use_stub=True):
    env = os.environ.copy()

    path_parts = [REPO_ROOT]
    if use_stub:
        path_parts.insert(0, STUBS_DIR)
    existing = env.get("PYTHONPATH", "")
    if existing:
        path_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(path_parts)

    # Test output contains characters cp1252 can't encode.
    env["PYTHONIOENCODING"] = "utf-8"

    if _ssl_is_broken():
        dll_dirs = _conda_dll_dirs()
        if dll_dirs:
            env["PATH"] = os.pathsep.join(dll_dirs + [env.get("PATH", "")])

    return env


def run_suite(path, env, verbose=False):
    """Returns (ok_count, fail_count, returncode, output)."""
    proc = subprocess.Popen(
        [sys.executable, path],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    out, _ = proc.communicate()
    text = out.decode("utf-8", "replace")

    if verbose:
        print(text)

    ok = fail = 0
    found = False
    for line in reversed(text.splitlines()):
        m = _RESULT_RE.search(line)
        if m:
            ok, fail = int(m.group(1)), int(m.group(2))
            found = True
            break

    if not found and proc.returncode != 0:
        fail = fail or 1

    return ok, fail, proc.returncode, text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-k", dest="pattern", default=None,
                        help="only run suites whose filename contains this")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="stream each suite's full output")
    parser.add_argument("--real-streamlit", action="store_true",
                        help="import the installed streamlit instead of the stub")
    args = parser.parse_args(argv)

    suites = discover(args.pattern)
    if not suites:
        print("No test suites found in %s" % TESTS_DIR)
        return 1

    use_stub = not args.real_streamlit
    if use_stub and not os.path.isfile(os.path.join(STUBS_DIR, "streamlit.py")):
        print("ERROR: streamlit stub missing at %s" % STUBS_DIR)
        return 1

    env = build_env(use_stub=use_stub)
    print("interpreter : %s" % sys.executable)
    print("streamlit   : %s" % ("offline stub (tests/_stubs)" if use_stub
                                else "installed package"))
    print("suites      : %d\n" % len(suites))

    total_ok = total_fail = 0
    broken = []
    width = max(len(os.path.basename(p)) for p in suites)

    for path in suites:
        name = os.path.basename(path)
        ok, fail, rc, text = run_suite(path, env, verbose=args.verbose)
        total_ok += ok
        total_fail += fail

        has_count = bool(_RESULT_RE.search(text))

        if fail == 0 and rc == 0:
            # test_catalogue.py predates the "N ok, M fail" convention and
            # self-reports with asserts; exit 0 is its only success signal.
            status = ("PASS  %4d ok" % ok) if has_count else "PASS  (asserts, no count)"
        elif has_count:
            status = "FAIL  %4d ok, %d fail" % (ok, fail)
            broken.append((name, text))
        else:
            status = "ERROR (no result line, exit %s)" % rc
            broken.append((name, text))

        print("  %-*s  %s" % (width, name, status))

    print("\n" + "-" * 60)
    print("TOTAL: %d ok, %d fail across %d suites" %
          (total_ok, total_fail, len(suites)))

    if broken and not args.verbose:
        print("\nFailing output:")
        for name, text in broken:
            print("\n=== %s " % name + "=" * (54 - len(name)))
            tail = text.strip().splitlines()
            for line in tail[-25:]:
                print("  " + line)

    return 0 if not broken else 1


if __name__ == "__main__":
    sys.exit(main())
