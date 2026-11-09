"""enforce lowercase user email

Revision ID: 2e25f9565a47
Revises: e798e252d359
Create Date: 2026-11-09 10:10:01.709259

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2e25f9565a47"
down_revision: str | Sequence[str] | None = "e798e252d359"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Exige email canônico sem reescrever linhas existentes."""
    connection = op.get_bind()
    # Para se já houver maiúscula. Não normaliza e não apaga.
    violating = connection.execute(
        sa.text("SELECT count(*) FROM users WHERE email IS DISTINCT FROM lower(email)")
    ).scalar_one()
    if violating:
        raise RuntimeError(
            "Há emails com maiúsculas em users. "
            "A migration não altera nem apaga essas linhas."
        )

    op.create_check_constraint(
        "ck_users_email_lowercase",
        "users",
        "email = lower(email)",
    )


def downgrade() -> None:
    """Remove só o CHECK. O UNIQUE(email) permanece."""
    op.drop_constraint("ck_users_email_lowercase", "users", type_="check")
