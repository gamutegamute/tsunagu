"""Add shelters.capacity (決定事項9・34-b: 避難所キャパシティの永続化)."""

from alembic import op

revision = "0003_shelter_capacity"
down_revision = "0002_incident_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE shelters ADD COLUMN IF NOT EXISTS capacity INTEGER CHECK (capacity IS NULL OR capacity >= 0);")


def downgrade() -> None:
    op.execute("ALTER TABLE shelters DROP COLUMN IF EXISTS capacity;")
