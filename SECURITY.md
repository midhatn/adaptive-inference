# Security and operational scope

Default deployment binds to loopback. Non-loopback configuration requires a gateway bearer credential named by environment variable. Use an authenticated HTTPS reverse proxy for network deployments. This release is not a tenant-isolation boundary.

Gateway credentials and backend credentials are separate. Metrics omit prompts, response bodies and credentials. Model servers and agents retain their own filesystem, tool and network permissions. The gateway does not authorize agent tools.

Report a vulnerability through GitHub's private vulnerability-reporting facility if enabled; otherwise use the maintainer contact shown on the GitHub profile without including secrets in a public issue. Do not publish real credentials or private task data as a reproducer.
