"""merge classifications into email_threads

Revision ID: 599ee49d2efb
Revises: 2eee13a60e20
Create Date: 2026-03-06 00:20:37.211097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '599ee49d2efb'
down_revision: Union[str, None] = '2eee13a60e20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('email_threads', sa.Column('category_id', sa.UUID(), nullable=True))
    op.add_column('email_threads', sa.Column('is_user_corrected', sa.Boolean(), nullable=True))
    op.add_column('email_threads', sa.Column('classified_at', sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        'fk_email_threads_category_id', 'email_threads', 'categories',
        ['category_id'], ['id'], ondelete='SET NULL'
    )

    op.execute("""
        UPDATE email_threads et
        SET category_id = c.category_id,
            is_user_corrected = c.is_user_corrected,
            classified_at = c.classified_at
        FROM classifications c
        WHERE c.email_thread_id = et.id
    """)

    op.alter_column('email_threads', 'is_user_corrected',
                     nullable=False, server_default=sa.text('false'))

    op.drop_table('classifications')


def downgrade() -> None:
    op.create_table('classifications',
        sa.Column('email_thread_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('category_id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('is_user_corrected', sa.BOOLEAN(), autoincrement=False, nullable=False),
        sa.Column('classified_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.Column('id', sa.UUID(), autoincrement=False, nullable=False),
        sa.Column('created_at', postgresql.TIMESTAMP(timezone=True), server_default=sa.text('now()'), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(['category_id'], ['categories.id'], name='classifications_category_id_fkey', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['email_thread_id'], ['email_threads.id'], name='classifications_email_thread_id_fkey', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name='classifications_pkey'),
        sa.UniqueConstraint('email_thread_id', name='classifications_email_thread_id_key')
    )

    op.execute("""
        INSERT INTO classifications (id, email_thread_id, category_id, is_user_corrected, classified_at, created_at)
        SELECT gen_random_uuid(), id, category_id, is_user_corrected, COALESCE(classified_at, now()), now()
        FROM email_threads
        WHERE category_id IS NOT NULL
    """)

    op.drop_constraint('fk_email_threads_category_id', 'email_threads', type_='foreignkey')
    op.drop_column('email_threads', 'classified_at')
    op.drop_column('email_threads', 'is_user_corrected')
    op.drop_column('email_threads', 'category_id')
