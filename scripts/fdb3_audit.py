"""Read-only ref/source inventories. Never execute competitor code or setup hooks."""
import argparse
import re
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


def git(*args, cwd=None, public=False):
    command = ["git"]
    env = os.environ.copy()
    if public:
        command += ["-c", "credential.helper=", "-c", "core.hooksPath=NUL", "-c", "gc.auto=0"]
        env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.check_output(command + list(args), cwd=cwd, env=env,
                                   text=True, encoding="utf-8", errors="replace", timeout=60).strip()


def own_audit(root):
    rows = []
    refs = git("for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads", "refs/remotes", cwd=root)
    for line in refs.splitlines():
        ref, commit = line.split()
        trees = git("ls-tree", "-d", commit, "participant", "thread_agent", "android", "web", cwd=root)
        rows.append({"ref": ref, "commit": commit, "runtime_trees": trees,
                     "equivalence_sha256": hashlib.sha256(trees.encode()).hexdigest()})
    return {"refs": rows, "unique_runtime_tree_sets": len({r["equivalence_sha256"] for r in rows})}


# Conservative identity: every tracked tree entry contributes, including locks,
# tests, assets, documentation and submodule commit IDs. No extension allowlist
# can establish equivalence of a runtime whose asset/config inputs are unknown.
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".kt", ".kts",
                   ".java", ".html", ".htm", ".css", ".scss", ".sh", ".ps1", ".bat",
                   ".go", ".rs", ".c", ".cpp", ".h", ".swift", ".dart", ".sql"}


def secret_path(path):
    name = Path(path).name.lower()
    return (name.startswith(".env") or name.endswith((".pem", ".key", ".p12", ".jks", ".keystore"))
            or any(word in name for word in ("credential", "secret", "service-account")))


def tree_identity(entries):
    return hashlib.sha256(json.dumps(entries, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def inspect_tree(destination, commit):
    listing = git("ls-tree", "-rz", commit, cwd=destination, public=True)
    entries = []
    for line in listing.split("\0"):
        if not line:
            continue
        metadata, path = line.split("\t", 1)
        mode, kind, oid = metadata.split()
        entries.append({"path":path, "mode":mode, "type":kind, "git_object_id":oid})
    entries.sort(key=lambda entry: entry["path"])
    # Only our Git parser reads blobs. No checkout, imports, hooks, or setup runs.
    selected = [e for e in entries if e["type"] == "blob" and not secret_path(e["path"])
                and Path(e["path"]).suffix.lower() in SOURCE_SUFFIXES]
    # Partial clones otherwise perform one network fetch per source blob.
    # Batch missing object reads to keep this static lane bounded and lightweight.
    env = os.environ.copy()
    env.update(GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    request = "\n".join(dict.fromkeys(e["git_object_id"] for e in selected)) + "\n"
    if selected:
        status = subprocess.check_output(["git", "cat-file", "--batch-check"], input=request,
                                         text=True, cwd=destination, env=env, timeout=60)
        missing = [line.split()[0] for line in status.splitlines() if line.endswith(" missing")]
        if missing:
            subprocess.run(["git", "-c", "credential.helper=", "-c", "core.hooksPath=NUL", "-c", "gc.auto=0",
                            "fetch", "--no-tags", "--no-auto-maintenance", "origin", "--stdin"],
                           input=("\n".join(missing)+"\n").encode(), cwd=destination,
                           env=env, check=True, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    sources = []
    for entry in selected:
        path = entry["path"]
        data = subprocess.check_output(["git", "-c", "credential.helper=", "-c", "core.hooksPath=NUL",
                                        "cat-file", "blob", entry["git_object_id"]], cwd=destination, env=env, timeout=60)
        content = data.decode("utf-8", errors="replace")
        sources.append({"path":path, "git_object_id":entry["git_object_id"],
                        "sha256":hashlib.sha256(data).hexdigest(), "bytes":len(data),
                        "lines":len(content.splitlines()),
                        "markers":{term:len(re.findall(term, content, re.I)) for term in
                                   ("livekit", "interrupt", "cancel", "revision", "epoch", "stale", "idempoten", "speechrecognition", "speechsynthesis")}})
    return entries, sources


def competitors(root, refresh=False):
    target = root / "docs/fdb3/competitor-inventory.json"
    previous = json.loads(target.read_text(encoding="utf-8"))
    rows, inspections = [], []
    for old in previous["repositories"]:
        repo, url = old["repository"], old["url"]
        destination = root / ".runtime/competitor-audit" / repo.replace("/", "--")
        row = {"repository":repo,"url":url,"status":"STATIC_INSPECTION", "measured_score":None,
               "execution":"BLOCKED: no verified credential-free OS sandbox; INR 0 paid budget",
               "variants":[], "tests_executed":False}
        try:
            row["refs"] = (git("ls-remote", "--heads", "--tags", url + ".git", public=True).splitlines()
                           if refresh else old.get("refs", []))
            row["refs_observed_at"] = datetime.now(timezone.utc).isoformat() if refresh else old.get("refs_observed_at", previous.get("observed_at"))
            if not row["refs"] or not destination.exists():
                raise RuntimeError("No accessible cached source/ref; previous status: " + old["status"])
            seen = {}
            for refline in row["refs"]:
                oid, ref = refline.split()
                if ref.endswith("^{}"):
                    continue
                try:
                    commit = git("rev-parse", oid + "^{commit}", cwd=destination, public=True)
                    entries, sources = inspect_tree(destination, commit)
                except subprocess.CalledProcessError:
                    if not refresh:
                        raise
                    git("fetch", "--no-tags", url + ".git", ref, cwd=destination, public=True)
                    commit = git("rev-parse", oid + "^{commit}", cwd=destination, public=True)
                    entries, sources = inspect_tree(destination, commit)
                fingerprint = tree_identity(entries)
                if fingerprint in seen:
                    seen[fingerprint]["refs"].append(ref)
                    seen[fingerprint]["ref_commits"][ref] = commit
                    continue
                variant = {"refs":[ref], "ref_commits":{ref:commit}, "commit":commit,
                           "tracked_tree_sha256":fingerprint, "tracked_files":entries,
                           "source_file_count":len(sources), "tests_executed":False, "live_score":None,
                           "build_test_entrypoints":[e for e in entries if
                               Path(e["path"]).name in {"package.json", "pyproject.toml", "requirements.txt", "requirements-dev.txt",
                                                        "Dockerfile", "Makefile", "gradlew", "build.gradle.kts", "pytest.ini"}
                               or e["path"].startswith(".github/workflows/")],
                           "test_paths":[e["path"] for e in entries if
                               any(part in {"tests", "test", "androidTest"} for part in Path(e["path"]).parts)
                               or Path(e["path"]).name.startswith("test_") or ".test." in e["path"]]}
                seen[fingerprint] = variant
                row["variants"].append(variant)
                inspections.append({"repository":repo,"commit":commit,"refs":variant["refs"],
                                    "tracked_tree_sha256":fingerprint,"source_files":sources,
                                    "tests_executed":False, "method":"Read-only blob hashing and lexical markers; markers are not behavioral validation"})
            row["distinct_tracked_trees"] = len(seen)
        except Exception as exc:
            row.update(status="BLOCKED", error=type(exc).__name__ + ": " + str(exc))
        rows.append(row)
        print(repo, row["status"], len(row["variants"]), flush=True)
    (root / "docs/fdb3/competitor-source-inspection.json").write_text(json.dumps(inspections,indent=2),encoding="utf-8")
    # Shared nontrivial blobs are evidence of overlap, not proof of copied authorship
    # or semantic equivalence. Runtime variants remain separate in the cohort.
    overlaps = []
    for index, a in enumerate(inspections):
        aset = {f["sha256"] for f in a["source_files"] if f["bytes"] >= 200}
        for b in inspections[index+1:]:
            if a["repository"] == b["repository"]:
                continue
            bset = {f["sha256"] for f in b["source_files"] if f["bytes"] >= 200}
            common = aset & bset
            if len(common) >= 3:
                overlaps.append({"a":a["repository"],"a_commit":a["commit"],"b":b["repository"],"b_commit":b["commit"],
                                 "shared_nontrivial_source_blobs":len(common),"a_source_blobs":len(aset),"b_source_blobs":len(bset),
                                 "identical_tracked_tree":a["tracked_tree_sha256"] == b["tracked_tree_sha256"],
                                 "shared_sha256":sorted(common)})
    (root / "docs/fdb3/competitor-overlap.json").write_text(json.dumps(overlaps,indent=2),encoding="utf-8")
    return {"schema_version":2,"searches":previous.get("searches",[]),"expanded_search_log":previous.get("expanded_search_log"),
            "repositories":rows,"exhaustive":False,"ref_refresh_performed":refresh,
            "summary":{"candidate_repositories":len(rows), "accessible_repositories":sum(r["status"] == "STATIC_INSPECTION" for r in rows),
                       "named_refs":sum(not ref.endswith("^{}") for r in rows for ref in r.get("refs",[])),
                       "peeled_tag_records":sum(ref.endswith("^{}") for r in rows for ref in r.get("refs",[])),
                       "per_repository_tracked_snapshots":len(inspections),
                       "unique_tracked_trees_across_repositories":len({v["tracked_tree_sha256"] for v in inspections}),
                       "source_file_observations":sum(len(v["source_files"]) for v in inspections)},
            "identity_method":"SHA-256 of sorted complete tracked path/mode/type/Git-object-id inventory. Identical tracked trees only; no semantic-equivalence claim. Blob SHA-256 for inspected source; dependencies/locks/assets remain in full tree identity.",
            "credential_contents_read":False,"tests_executed":False,
            "limitations":["Submodule contents and Git LFS payloads not dereferenced", "External dependencies, services and untracked runtime files unverified", "No build, test, dependency installation or competitor code execution"]}


def self_check():
    base = [{"path":"app.py", "mode":"100644", "type":"blob", "git_object_id":"a"}]
    for path in ("App.tsx", "Main.kt", "Main.java", "index.html", "package-lock.json", "test.py"):
        changed = base + [{"path":path, "mode":"100644", "type":"blob", "git_object_id":"b"}]
        assert tree_identity(base) != tree_identity(changed), path
        assert tree_identity(changed) != tree_identity([dict(e, git_object_id="c") for e in changed]), path
    assert secret_path(".env.example") and secret_path("keys/private.pem")
    assert not secret_path("app/src/Main.kt")
    print("audit self-check passed: omitted languages, locks, tests affect identity")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--competitors", action="store_true")
    parser.add_argument("--refresh-refs", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        root = Path(__file__).resolve().parents[1]
        result = competitors(root, args.refresh_refs) if args.competitors else own_audit(root)
        result["observed_at"] = datetime.now(timezone.utc).isoformat()
        target = root / "docs/fdb3" / ("competitor-inventory.json" if args.competitors else "branch-inventory.json")
        target.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(target)
