# Local portal expiry comparison (Windows run)

On 23 November 2026, Windows 11, Python 3.14.0 and Node.js 24.12.0, a disposable local instance ran the code from [Documentalist PR #25](https://github.com/azerothl/documentalist/pull/25) on top of `947429b`, with Next.js 16.4.6. No real account, email or deployed portal was used.

The script initialized the portal and a fictional editor, created a private space and one invitation, and compared the OpenGuildKit register with the portal using `docs share verify`'s implementation. A future UTC end date produced a matching, active invitation policy. The script then set the portal and register to a past date; the next observation matched and reported the policy inactive. The observation identified the source as `documentalist-api` and was written beside the local register. These checks change the date to exercise both states; they do not wait for midnight or verify a real email delivery. The portal's HTTP suite separately covers an old link, an established session, a new request and manual revocation.

`tests.test_portal_verification` covers a compatible API, an older API without expiry support, overlapping shares and a refused authentication redirect. On the same machine, `tests.test_publishing` and that module ran 41 tests with four platform-dependent skips.

To repeat the integration exercise, build the Documentalist PR checkout with its npm dependencies, then run from an OpenGuildKit checkout:

```bash
PYTHONPATH=src python examples/documentalist/verify-expiry.py --documentalist /path/to/documentalist
```

The script starts a server on loopback, creates a temporary data directory and stops the server afterwards. It requires Node.js, a built Documentalist checkout and the checkout's npm dependencies. Before adopting this on a dedicated instance, repeat the check against its released version and confirm its reader session and SMTP behavior there.
