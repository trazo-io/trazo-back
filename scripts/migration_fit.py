"""Does each open PR's new migrations still build on main's latest migration?

Why: CI runs `makemigrations --check` on a PR against main as it was when the PR's CI ran. Two
PRs that each add the next migration of an app both pass, and whichever merges second leaves the
app with two leaf migrations. `migrate` then refuses to run ("Conflicting migrations detected")
and the production deploy fails: history 0247 (2026-10-21, repaired by 0248) and history 0256
(2026-11-11, repaired by renumbering in #373). Branch protection does not require a PR to be up
to date with main, so nothing re-checks a PR when main moves.

This runs on every push to main and every PR event, over ALL open PRs into main, and posts a
commit status on each PR head (`STATUS_CONTEXT`, a required check). For each app a PR adds
migrations to, the migrations it builds on from outside the PR must be main's current leaf; if
one is older, merging would make two leaves, and the status fails with what to renumber. It also
comments on every open PR that builds on the same migration as another open PR: both pass now,
and whichever merges second must renumber. That comment is the only warning for two merges
closer together than this workflow's run time.

Standard library only (no Django): migrations are read with `ast`, so the job needs no install.
The app label is the directory holding `migrations/`, which is the label for every app here.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

STATUS_CONTEXT = "Migrations fit current main"
MARKER = "<!-- migration-fit -->"
MIGRATION_PATH = re.compile(r"^(?P<app>[^/]+)/migrations/(?P<name>\d{4}_\w+)\.py$")


def migration_of(path):
    """(app, name) for a numbered migration file path, else None."""
    match = MIGRATION_PATH.match(path)
    return (match["app"], match["name"]) if match else None


def dependencies(source):
    """The literal (app, name) pairs in a migration's `dependencies`.

    Non-literal entries (`migrations.swappable_dependency(...)`) are skipped: they point at another
    app's migration, never at this app's chain.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef) and node.name == "Migration":
            for statement in node.body:
                if (
                    isinstance(statement, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "dependencies" for t in statement.targets)
                    and isinstance(statement.value, (ast.List, ast.Tuple))
                ):
                    pairs = []
                    for element in statement.value.elts:
                        try:
                            value = ast.literal_eval(element)
                        except ValueError:
                            continue
                        if isinstance(value, tuple) and len(value) == 2:
                            pairs.append((str(value[0]), str(value[1])))
                    return pairs
    return []


def app_graph(files):
    """{app: {name: {names in the same app it depends on}}} for {path: source}."""
    graph = defaultdict(dict)
    for path, source in files.items():
        found = migration_of(path)
        if not found:
            continue
        app, name = found
        graph[app][name] = {dep for dep_app, dep in dependencies(source) if dep_app == app}
    return graph


def leaves(chain):
    """Migrations of one app that no other migration of that app depends on."""
    depended_on = set().union(*chain.values()) if chain else set()
    return set(chain) - depended_on


def anchors(main_files, added_files):
    """{app: {main migrations the PR's new migrations build on}} for each app the PR adds to."""
    added = app_graph(added_files)
    result = {}
    for app, chain in added.items():
        new = set(chain) - set(app_graph(main_files).get(app, {}))
        result[app] = {dep for name in new for dep in chain[name] if dep not in chain}
    return result


def problems(main_files, added_files):
    """Why merging these added migrations into main would leave an app with two leaves."""
    main = app_graph(main_files)
    found = []
    for app, built_on in sorted(anchors(main_files, added_files).items()):
        current = leaves(main.get(app, {}))
        stale = sorted(built_on - current)
        if not stale:
            continue
        new = sorted(set(app_graph(added_files)[app]) - set(main.get(app, {})))
        found.append(
            f"{app}: {', '.join(new)} builds on {', '.join(stale)}, but main's latest {app} migration is now "
            f"{', '.join(sorted(current))}. Renumber it to follow {', '.join(sorted(current))} (change its "
            "number and its dependency), then push."
        )
    return found


def shared_anchors(per_pr_anchors):
    """{pr: [(app, migration, [other prs])]} for PRs building on the same migration as another."""
    by_anchor = defaultdict(set)
    for pr, apps in per_pr_anchors.items():
        for app, built_on in apps.items():
            for migration in built_on:
                by_anchor[(app, migration)].add(pr)
    shared = defaultdict(list)
    for (app, migration), prs in sorted(by_anchor.items()):
        if len(prs) > 1:
            for pr in prs:
                shared[pr].append((app, migration, sorted(prs - {pr})))
    return dict(shared)


# --- git and GitHub plumbing (exercised by the workflow, not the unit tests) ---------------------


def _run(*args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs).stdout


def _sources(ref, paths):
    return {path: _run("git", "show", f"{ref}:{path}") for path in paths}


def _main_files(base, apps):
    paths = [
        p
        for p in _run("git", "ls-tree", "-r", "--name-only", base).splitlines()
        if (found := migration_of(p)) and found[0] in apps
    ]
    return _sources(base, paths)


def _added_files(base, head):
    names = _run("git", "diff", "--name-only", "--diff-filter=A", f"{base}...{head}").splitlines()
    return _sources(head, [p for p in names if migration_of(p)])


def _gh(*args, payload=None):
    return _run("gh", *args, input=json.dumps(payload) if payload is not None else None)


def _marked_comments(repo, number):
    pages = json.loads(_gh("api", f"repos/{repo}/issues/{number}/comments", "--paginate", "--slurp"))
    return [c for page in pages for c in page if MARKER in (c.get("body") or "")]


def _say(repo, number, body, only_if_one_exists=False):
    """Keep ONE marked comment per PR: edit it in place, create it only when there is news."""
    mine = _marked_comments(repo, number)
    if mine:
        if mine[-1]["body"] != body:
            path = f"repos/{repo}/issues/comments/{mine[-1]['id']}"
            _gh("api", "-X", "PATCH", path, "--input", "-", payload={"body": body})
    elif not only_if_one_exists:
        _gh("api", f"repos/{repo}/issues/{number}/comments", "--input", "-", payload={"body": body})


def _comment_body(found, shared, head_of_main):
    lines = []
    if found:
        lines += [
            "**These migrations no longer fit main.** Merging this would leave an app with two leaf "
            "migrations, and the deploy would fail at `migrate`.",
            "",
            *[f"- {p}" for p in found],
        ]
    for app, migration, others in shared:
        names = ", ".join(f"#{o}" for o in others)
        lines.append(
            f"- Heads up: {names} also build{'s' if len(others) == 1 else ''} on `{app}` `{migration}`. "
            "Each passes on its own; whichever merges second must renumber."
        )
    return "\n".join([MARKER, *lines, "", f"Checked against main {head_of_main}."]) if lines else ""


def _post(repo, sha, state, description, run_url):
    status = {"state": state, "context": STATUS_CONTEXT, "description": description[:140], "target_url": run_url}
    _gh("api", f"repos/{repo}/statuses/{sha}", "--input", "-", payload=status)


def check_open_prs(repo, base, run_url):
    """Check and post per PR. One PR that cannot be read (branch deleted or force-pushed since the
    listing, a migration that is not valid Python) gets an `error` status; the others still get
    theirs. Returns the number of PRs that could not be checked or posted."""
    listing = _gh(
        "pr", "list", "--repo", repo, "--base", "main", "--state", "open", "--limit", "200",
        "--json", "number,headRefOid",
    )  # fmt: skip
    head_of_main = _run("git", "rev-parse", "--short", base).strip()
    results, per_pr_anchors, errors = {}, {}, 0
    for pr in json.loads(listing):
        number, sha = pr["number"], pr["headRefOid"]
        try:
            _run("git", "fetch", "--no-tags", "--quiet", "origin", f"pull/{number}/head:refs/pr/{number}")
            added = _added_files(base, f"refs/pr/{number}")
            main = _main_files(base, {migration_of(p)[0] for p in added})
            results[number] = (sha, problems(main, added))
            per_pr_anchors[number] = anchors(main, added)
        except (subprocess.CalledProcessError, SyntaxError, ValueError) as exc:
            errors += 1
            detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else repr(exc)
            print(f"#{number} error: could not be checked: {detail}")
            try:
                _post(
                    repo,
                    sha,
                    "error",
                    f"could not be checked against main {head_of_main}: {type(exc).__name__}",
                    run_url,
                )
            except subprocess.CalledProcessError as post_exc:
                print(f"#{number} error: status not posted: {post_exc.stderr.strip()}")
    shared = shared_anchors(per_pr_anchors)
    for number, (sha, found) in sorted(results.items()):
        state = "failure" if found else "success"
        description = f"needs renumbering against main {head_of_main}" if found else f"fits main {head_of_main}"
        try:
            _post(repo, sha, state, description, run_url)
            body = _comment_body(found, shared.get(number, []), head_of_main)
            if body:
                _say(repo, number, body)
            else:  # nothing to say now: close out an earlier warning, never open a new comment
                resolved = f"{MARKER}\nResolved: the migrations fit main {head_of_main}."
                _say(repo, number, resolved, only_if_one_exists=True)
        except subprocess.CalledProcessError as exc:
            errors += 1
            print(f"#{number} error: status or comment not posted: {exc.stderr.strip()}")
            continue
        print(f"#{number} {state}: {description}")
        for p in found:
            print(f"  {p}")
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("check", help="Check one head ref against a base ref, locally; exit 1 if it does not fit.")
    one.add_argument("--base", default="origin/main")
    one.add_argument("--head", required=True)
    every = sub.add_parser("check-open-prs", help="Check every open PR into main and post a status on each.")
    every.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)
    if args.command == "check":
        added = _added_files(args.base, args.head)
        found = problems(_main_files(args.base, {migration_of(p)[0] for p in added}), added)
        print("\n".join(found) or f"fits {args.base}")
        return 1 if found else 0
    env = os.environ
    run_url = f"{env['GITHUB_SERVER_URL']}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    # The statuses carry each PR's verdict; the job itself goes red only when a PR could not be
    # checked or posted, which is a problem with this job rather than with the PR.
    return 1 if check_open_prs(env["GITHUB_REPOSITORY"], args.base, run_url) else 0


if __name__ == "__main__":
    sys.exit(main())
