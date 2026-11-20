#!/usr/bin/env bash
# Keep the "Full Changelog" link of release notes on a revision GitHub can compare.
#
#   release-notes.sh draft SHA          refresh the openguildkit-next draft for main at SHA
#   release-notes.sh published TAG ID   point the link of a published release to its tag
#
# Needs GH_REPO and GH_TOKEN. With DRY_RUN=1, prints the new body instead of writing it.
set -euo pipefail

releases="/repos/$GH_REPO/releases"
draft_tag=openguildkit-next

write_release() {
  local method=$1 endpoint=$2 payload=$3
  if [[ "${DRY_RUN:-}" == 1 ]]; then
    jq -r .body <<< "$payload"
    return
  fi
  gh api --method "$method" "$endpoint" --input - --silent <<< "$payload"
}

draft() {
  local sha=$1 existing draft_id method endpoint previous link notes body
  existing=$(gh api --paginate --slurp "$releases?per_page=100")

  if jq -e --arg tag "$draft_tag" 'any(.[][]; .tag_name == $tag and (.draft | not))' <<< "$existing" >/dev/null; then
    printf 'Tag %s is already attached to a published release.\n' "$draft_tag" >&2
    exit 1
  fi

  draft_id=$(jq -r --arg tag "$draft_tag" '.[][] | select(.draft and .tag_name == $tag) | .id' <<< "$existing")
  if [[ -n "$draft_id" ]]; then
    method=PATCH
    endpoint="$releases/$draft_id"
  else
    method=POST
    endpoint="$releases"
  fi

  # The draft tag does not exist in Git, so compare from the last published release to the commit.
  previous=$(jq -r '[.[][] | select(.draft | not)] | sort_by(.published_at) | last | .tag_name // empty' <<< "$existing")
  local args=(-f tag_name="$draft_tag" -f target_commitish="$sha" -f configuration_file_path=.github/release.yml)
  if [[ -n "$previous" ]]; then
    args+=(-f previous_tag_name="$previous")
    link="https://github.com/$GH_REPO/compare/$previous...$sha"
  else
    link="https://github.com/$GH_REPO/commits/$sha"
  fi

  notes=$(gh api --method POST "$releases/generate-notes" "${args[@]}" --jq .body)
  body=$(jq -rn --arg notes "$notes" --arg link "$link" '
    ($notes | split("\n") | map(select(startswith("**Full Changelog**") | not)) | join("\n") | rtrimstr("\n"))
    + "\n\n**Full Changelog**: " + $link')

  write_release "$method" "$endpoint" "$(jq -n --arg tag "$draft_tag" --arg body "$body" \
    '{tag_name: $tag, target_commitish: "main", name: "Next release (automated draft)", draft: true, body: $body}')"
}

published() {
  local tag=$1 id=$2 body updated
  body=$(gh api "$releases/$id" --jq '.body // ""')
  # A body copied from the draft ends its comparison on a commit SHA. Use the release tag instead.
  updated=$(jq -rn --arg body "$body" --arg tag "$tag" '$body
    | gsub("(?<base>/compare/[^\\s)]+?\\.\\.\\.)[0-9a-f]{40}\\b"; "\(.base)\($tag)")
    | gsub("(?<base>/commits/)[0-9a-f]{40}\\b"; "\(.base)\($tag)")')
  if [[ "$updated" == "$body" ]]; then
    printf 'The release notes of %s already end on a tag.\n' "$tag"
    return
  fi
  write_release PATCH "$releases/$id" "$(jq -n --arg body "$updated" '{body: $body}')"
}

case "${1:-}" in
  draft) draft "$2" ;;
  published) published "$2" "$3" ;;
  *) printf 'Usage: %s draft SHA | published TAG RELEASE_ID\n' "$0" >&2; exit 2 ;;
esac
