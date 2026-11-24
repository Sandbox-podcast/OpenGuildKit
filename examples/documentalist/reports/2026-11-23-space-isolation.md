# Documentalist, 23 November 2026: isolate a share in its own space

OpenGuildKit issue [#266](https://github.com/Sandbox-podcast/OpenGuildKit/issues/266)
proposes a private space per independently revocable deliverable. Each space
keeps its own reader list and published copy. Existing spaces keep their current
space-wide access. OpenGuildKit records each dedicated portal and its revocation
in the existing register. The approach is ready for maintainer review.

## Local validation

The test ran on Windows with Node 22.20.0, Next.js 16.4.3 and the existing local
Documentalist build. The source revision of that build is unknown. The instance
listened on loopback with a fresh data directory and a local SMTP sink. All
documents and accounts were synthetic.

1. As administrator, create two spaces and import a different Markdown page in
   each. Give each page and space a distinct title. Select magic-link access in
   both spaces, invite a different address in each, and publish both.
2. In a separate reader session, redeem the first space's invitation. Open the
   first portal, the second portal and the direct URL of the second page.
   In the first portal, search for a phrase unique to the first page, then
   for one unique to the second.
3. Invite the first reader to the second space and redeem that invitation in the
   same session. Confirm the second page now opens. Remove that reader from the
   first space and revisit both portals in the same session.
4. Edit the second page, publish the source space again and open the same
   address with the existing reader session. Then publish a copy of that
   revision in a third space whose only invitee is a different reader.
   Remove the source page, publish the source space again and check the old
   URL and the destination with the old reader session.

| Check | Observed |
| --- | --- |
| First invitation | The first page was readable. The second space's title, link and page content were absent from the first portal response. |
| Second portal and direct page URL with only the first invitation | Both responses withheld the second page's content. |
| Same reader across both spaces | The second direct URL opened after the second invitation. Removing the first invitation ended the first space's access and the second page stayed readable. |
| Search in Edge | A phrase from the shared page returned that page. A phrase from the second space produced no results. |
| New publication in the same space | The reader still saw the first revision until publication. The same session opened the updated page at the same URL afterwards. |
| Replacement in a different space | The old invite did not grant access to the destination. The old URL served the previous publication until the source space was republished. The old page then disappeared. |

The maintainers still need to validate the model and repeat the recipe on the
Documentalist version chosen for the pilot.
