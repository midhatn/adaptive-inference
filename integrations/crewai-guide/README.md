# CrewAI shared-admission documentation check

The four localized sections here are our proposed addition to CrewAI's current
`docs/edge/*/concepts/llms.mdx`, based on source
`07361f6dc5f96d22efe565ff89297d22bce4a90f`. No upstream page content is copied.
They use the existing public LLM constructor and do not modify CrewAI runtime.

Use the dependency environment described in `../../provenance/python-clients`,
then run `python check-guide.py` here. It compares all four executable snippets,
constructs both real clients and sends two requests to loopback HTTP fixtures.
It checks model, nested route, credential, output and reasoning allowances and
projection/PCIe controls. External connections are denied. No model or actual
gateway is run. The temporary fixture settings contain dummy credentials only.

The original exact upstream-document snippets passed before export. The first
test runner attempted Windows cleanup while still inside its temporary working
directory; that harness cleanup failed after the assertions. The corrected
runner retains its temporary fixture directory and restores the working directory.
No client runtime was changed to obtain the result.

All four changed MDX pages also compile with the MDX compiler used by Mintlify.
Full-site validation is blocked by an existing frontmatter error in
`docs/edge/ko/tools/ai-ml/ragtool.mdx` at the unchanged upstream revision above.
This documentation addition does not alter that unrelated page.
