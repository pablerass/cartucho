#!/usr/bin/env bash
# Cut a release: bump the version, commit, tag and (for major/minor) create
# the release branch. See docs/releasing.md.
#
# Usage: scripts/release.sh major|minor|patch
#
# Environment:
#   DRY_RUN=1  only print what would be done
#   PUSH=1     push the branches and tag when done (this publishes to PyPI)
#   REMOTE     remote to check against and push to (default: origin)
#   MAIN       main branch name (default: main)
set -euo pipefail

remote=${REMOTE:-origin}
main=${MAIN:-main}

die() { echo "error: $*" >&2; exit 1; }

[[ $# -eq 1 && $1 =~ ^(major|minor|patch)$ ]] || die "usage: $0 major|minor|patch"
part=$1

cd "$(git rev-parse --show-toplevel)"

[[ -z $(git status --porcelain) ]] || die "the working tree has uncommitted changes"
branch=$(git symbolic-ref --quiet --short HEAD) || die "HEAD is detached"

git fetch --quiet --tags "$remote"
if git rev-parse --quiet --verify "refs/remotes/$remote/$branch" >/dev/null &&
    ! git merge-base --is-ancestor "$remote/$branch" HEAD; then
    die "$branch is behind $remote/$branch; pull first"
fi

current=$(sed -n 's/^current_version = "\(.*\)"$/\1/p' pyproject.toml)
[[ $current =~ ^v([0-9]+)\.([0-9]+)\.([0-9]+)(.*)$ ]] || die "unexpected current version '$current'"
major=${BASH_REMATCH[1]} minor=${BASH_REMATCH[2]} patch=${BASH_REMATCH[3]} pre=${BASH_REMATCH[4]}

# A pre-release (e.g. 0.1.0a1) comes before its final version, so the first
# release after it is that final version (0.1.0), not the next one.
case $part in
    major|minor)
        [[ $branch == "$main" ]] || die "$part releases are cut from $main, not $branch"
        if [[ $part == major ]]; then
            if [[ -n $pre && $minor == 0 && $patch == 0 ]]; then new="$major.0.0"; else new="$((major + 1)).0.0"; fi
        else
            if [[ -n $pre && $patch == 0 ]]; then new="$major.$minor.0"; else new="$major.$((minor + 1)).0"; fi
        fi
        release_branch="release/${new%.*}"
        if git rev-parse --quiet --verify "refs/heads/$release_branch" >/dev/null ||
            git rev-parse --quiet --verify "refs/remotes/$remote/$release_branch" >/dev/null; then
            die "$release_branch already exists"
        fi
        ;;
    patch)
        [[ $branch =~ ^release/([0-9]+)\.([0-9]+)$ ]] || die "patch releases are cut from a release/X.Y branch, not $branch"
        [[ ${BASH_REMATCH[1]}.${BASH_REMATCH[2]} == "$major.$minor" && -z $pre ]] ||
            die "$branch holds version $current; expected a final $major.$minor.x version"
        new="$major.$minor.$((patch + 1))"
        release_branch=$branch
        ;;
esac

tag="v$new"
git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null && die "tag $tag already exists"

if [[ $part == patch ]]; then
    push_refs=("$release_branch" "$tag")
else
    push_refs=("$main" "$release_branch" "$tag")
fi

echo "Releasing $current -> $tag from $branch (branch: $release_branch)"
if [[ -n ${DRY_RUN:-} ]]; then
    echo "Dry run: nothing changed. Would push: git push --atomic $remote ${push_refs[*]}"
    exit 0
fi

# Undo the file changes if anything fails before the commit.
trap 'git checkout --quiet -- . ; die "release failed; changes reverted"' ERR
uv run --quiet bumpver update --no-fetch --ignore-vcs-tag --set-version "$tag"
uv lock --quiet  # uv.lock records the project version
git commit --quiet --all --message "Bump version $current -> $tag"
trap - ERR

git tag --annotate "$tag" --message "cartucho $tag"
[[ $part == patch ]] || git branch "$release_branch"

echo "Created commit $(git rev-parse --short HEAD) and tag $tag on $release_branch"
if [[ -n ${PUSH:-} ]]; then
    git push --atomic "$remote" "${push_refs[@]}"
else
    echo "To publish it: git push --atomic $remote ${push_refs[*]}"
fi
