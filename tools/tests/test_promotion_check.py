import subprocess
from pathlib import Path

import pytest

import promotion_check
from promotion_check import environment_paths, image_refs, is_commit, violations

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def application(name: str, namespace: str, path: str) -> str:
    return f"""\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {name}
spec:
  source:
    repoURL: git@github.com:example/repo.git
    path: {path}
  destination:
    namespace: {namespace}
"""


def cronjob(image: str) -> str:
    return f"""\
apiVersion: batch/v1
kind: CronJob
metadata:
  name: job
spec:
  jobTemplate:
    spec:
      template:
        spec:
          initContainers:
            - name: ingest
              image: {image}
          containers:
            - name: transform
              image: {image}
"""


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def commit(repo: Path, files: dict[str, str], message: str) -> str:
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real Git repository with a staging and a prod Application and no images yet."""
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@example.com")
    git(tmp_path, "config", "user.name", "test")
    git(tmp_path, "config", "commit.gpgsign", "false")
    commit(
        tmp_path,
        {
            "platform/infra/apps/staging.yaml": application("staging", "staging", "env/staging"),
            "platform/infra/apps/prod.yaml": application("prod", "prod", "env/prod"),
            "env/staging/.keep": "",
            "env/prod/.keep": "",
        },
        "apps",
    )
    return tmp_path


def test_environment_paths_maps_namespace_to_git_paths(repo: Path) -> None:
    paths = environment_paths(repo / "platform/infra/apps")
    assert paths == {"staging": ["env/staging"], "prod": ["env/prod"]}


def test_image_refs_reads_container_images_and_cnpg_image_name(repo: Path) -> None:
    cluster = f"kind: Cluster\nspec:\n  imageName: pg:18@{DIGEST_B}\n"
    commit(repo, {"env/prod/job.yaml": cronjob(f"app:1@{DIGEST_A}"), "env/prod/pg.yaml": cluster},
           "prod")  # fmt: skip
    refs = image_refs(repo, ["env/prod"])
    assert refs == [
        ("env/prod/job.yaml", f"app:1@{DIGEST_A}"),
        ("env/prod/job.yaml", f"app:1@{DIGEST_A}"),
        ("env/prod/pg.yaml", f"pg:18@{DIGEST_B}"),
    ]


def test_passes_when_staging_pinned_the_digest_before_base(repo: Path) -> None:
    base = commit(repo, {"env/staging/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "staging bump")
    commit(repo, {"env/prod/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "prod promotion")
    assert violations(repo, base)[0] == []


def test_fails_when_one_change_pins_staging_and_prod_together(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    commit(
        repo,
        {
            "env/staging/job.yaml": cronjob(f"app:1@{DIGEST_A}"),
            "env/prod/job.yaml": cronjob(f"app:1@{DIGEST_A}"),
        },
        "both at once",
    )
    problems, _ = violations(repo, base)
    assert len(problems) == 2  # one per container
    assert all("was never pinned in staging" in p for p in problems)


def test_passes_when_staging_has_moved_on_to_a_newer_digest(repo: Path) -> None:
    commit(repo, {"env/staging/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "staging A")
    base = commit(repo, {"env/staging/job.yaml": cronjob(f"app:2@{DIGEST_B}")}, "staging B")
    commit(repo, {"env/prod/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "prod A")
    assert violations(repo, base)[0] == []


def test_fails_on_a_digest_staging_never_pinned(repo: Path) -> None:
    base = commit(repo, {"env/staging/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "staging A")
    commit(repo, {"env/prod/job.yaml": cronjob(f"app:2@{DIGEST_B}")}, "prod B")
    problems, _ = violations(repo, base)
    assert problems and all(DIGEST_B in p for p in problems)


def test_digest_only_outside_staging_paths_does_not_count(repo: Path) -> None:
    base = commit(repo, {"docs/notes.md": f"next: app:1@{DIGEST_A}\n"}, "a note")
    commit(repo, {"env/prod/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "prod A")
    assert violations(repo, base)[0]


def test_fails_on_an_image_without_a_digest(repo: Path) -> None:
    base = commit(repo, {"env/staging/job.yaml": cronjob("app:1")}, "staging tag")
    commit(repo, {"env/prod/job.yaml": cronjob("app:1")}, "prod tag")
    problems, _ = violations(repo, base)
    assert problems and all("not pinned by digest" in p for p in problems)


def test_is_commit_rejects_an_unknown_ref(repo: Path) -> None:
    assert is_commit(repo, "HEAD")
    assert not is_commit(repo, "0" * 40)
    assert not is_commit(repo, "no-such-branch")


def test_counts_the_images_it_checked(repo: Path) -> None:
    base = commit(repo, {"env/staging/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "staging A")
    commit(repo, {"env/prod/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "prod A")
    assert violations(repo, base) == ([], 2)


def test_fails_when_prod_has_no_image_to_check(repo: Path) -> None:
    base = git(repo, "rev-parse", "HEAD")
    problems, checked = violations(repo, base)
    assert checked == 0
    assert problems == ["no image found in env/prod: nothing was checked"]


def test_fails_when_a_prod_path_does_not_exist(repo: Path) -> None:
    base = commit(repo, {"env/staging/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "staging A")
    commit(repo, {"platform/infra/apps/prod.yaml": application("prod", "prod", "env/prd")}, "typo")
    problems, _ = violations(repo, base)
    assert "env/prd: prod Application path does not exist" in problems


def test_multi_source_application_uses_only_its_git_path(repo: Path) -> None:
    multi = """\
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prod
spec:
  sources:
    - repoURL: https://charts.example.com
      chart: something
      targetRevision: 1.0.0
    - repoURL: git@github.com:example/repo.git
      targetRevision: main
      ref: values
    - repoURL: git@github.com:example/repo.git
      path: env/prod
  destination:
    namespace: prod
"""
    commit(repo, {"platform/infra/apps/prod.yaml": multi}, "multi-source prod")
    assert environment_paths(repo / "platform/infra/apps")["prod"] == ["env/prod"]


def test_main_exit_codes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = commit(repo, {"env/staging/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "staging A")
    commit(repo, {"env/prod/job.yaml": cronjob(f"app:1@{DIGEST_A}")}, "prod A")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    def run(*args: str) -> int:
        monkeypatch.setattr("sys.argv", ["promotion_check.py", "--repo", str(repo), *args])
        return promotion_check.main()

    assert run("--base", base) == 0
    assert run("--base", "no-such-ref") == 2
    commit(repo, {"env/prod/job.yaml": cronjob(f"app:2@{DIGEST_B}")}, "prod B")
    assert run("--base", base) == 1
