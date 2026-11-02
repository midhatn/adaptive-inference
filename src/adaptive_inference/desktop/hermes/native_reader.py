# SPDX-License-Identifier: Apache-2.0
"""Use the pinned SDK's public readonly SessionDB inside the retained offload."""
from pathlib import Path
import os
import site
import sys

from adaptive_inference.desktop.installation import verify_sdk, verify_sdk_imports
from adaptive_inference.desktop.hermes.recovery import native_history


def native_reader_factory(source, site_packages, *, home):
    """Initialize once in the dedicated host, with an isolated SDK home.

    Reuses the installed worker's explicit dependency/home setup. Only this
    process environment changes; SDK initialization files stay in the fresh
    application run, not a user's normal Hermes home or saved task directory.
    """
    root = verify_sdk(source)
    dependencies = Path(site_packages).resolve(strict=True)
    if not dependencies.is_dir():
        raise ValueError('Explicit installed Hermes dependency directory required')
    home = Path(home)
    if not home.is_absolute() or home.parent.resolve(strict=True) != home.parent:
        raise ValueError('Fresh isolated native-reader home required')
    home.mkdir(exist_ok=False)
    for key in list(os.environ):
        if key.startswith(('HERMES_', 'OPENAI_', 'ANTHROPIC_')):
            os.environ.pop(key, None)
    os.environ.update(HERMES_HOME=str(home), HERMES_BUNDLED_PLUGINS=str(home/'empty-bundled'),
                      LITELLM_LOCAL_MODEL_COST_MAP='True')
    site.addsitedir(str(dependencies))
    verify_sdk_imports(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from hermes_state import SessionDB
    verify_sdk_imports(root)

    def read(task_root, session_id):
        path = Path(task_root)/'home/state.db'
        if not path.is_file():
            raise RuntimeError('Selected native session database is missing')
        db = SessionDB(path, read_only=True)
        try:
            if db.read_only is not True:
                raise RuntimeError('Native reader is not readonly')
            return native_history(db, session_id)
        finally:
            db.close()
    return read
