# Task preparation and historical source checks

The ordinary [prepare-task command](../../docs/task-spec.md#prepare-your-own-task)
adds one authoring module and a CLI dispatch. It does not alter task execution,
resource policy, the model or the existing TaskSpec contract.

Earlier source checks describe the exact 60-module runtime used by the installed
experiment. They must remain meaningful after a new feature expands the current
package. The [source record](source-lineage.json) and [retained CLI](cli.before.py)
let the existing test utilities validate the declared addition and CLI change,
then supply the original source bytes to those historical checks. Their module
membership, hashes and acceptance assertions remain intact. Current preparation
behavior is checked separately by [its functional tests](../../tests/test_task_prepare.py).

The correction addresses the actual hosted failure at commit
`6e17f3185e715013155d355aa05ff289c31bfab4`: historical module enumeration rejected
the new helper before later tests ran. That failed attempt remains failed.
No historical runtime is executed, no physical test is repeated, and no model
result is inferred from this source-only validation. The original interaction
sources and citations are retained in the task guide and bibliography.
