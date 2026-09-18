"""Initial isolated schema. Frozen DDL; later changes require a new migration."""

from alembic import op

revision = "0001"
down_revision = None


def upgrade():
    op.execute(
        "CREATE TABLE courses (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tnormalized_name VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (normalized_name)\n)"
    )
    op.execute(
        "CREATE TABLE credentials (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute(
        "CREATE TABLE events (\n\tseq INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, \n\tcreated_at VARCHAR NOT NULL, \n\tdata JSON NOT NULL\n)"
    )
    op.execute("CREATE INDEX ix_events_created_at ON events (created_at)")
    op.execute(
        "CREATE TABLE idempotency_keys (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute(
        "CREATE TABLE jobs (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tstate VARCHAR NOT NULL, \n\tslot VARCHAR, \n\tkind VARCHAR NOT NULL, \n\tlesson_id VARCHAR, \n\tsource_id VARCHAR, \n\tparent_id VARCHAR, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute("CREATE INDEX ix_jobs_kind ON jobs (kind)")
    op.execute("CREATE INDEX ix_jobs_lesson_id ON jobs (lesson_id)")
    op.execute("CREATE INDEX ix_jobs_parent_id ON jobs (parent_id)")
    op.execute("CREATE INDEX ix_jobs_source_id ON jobs (source_id)")
    op.execute("CREATE INDEX ix_jobs_state ON jobs (state)")
    op.execute(
        "CREATE UNIQUE INDEX uq_active_job_slot ON jobs (slot) WHERE slot IS NOT NULL AND state IN ('queued','running','cancelling')"
    )
    op.execute(
        "CREATE TABLE settings (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tPRIMARY KEY (id)\n)"
    )
    op.execute(
        "CREATE TABLE lessons (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tcourse_id VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(course_id) REFERENCES courses (id) ON DELETE RESTRICT\n)"
    )
    op.execute("CREATE INDEX ix_lessons_course_id ON lessons (course_id)")
    op.execute(
        "CREATE TABLE audio_sources (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tlesson_id VARCHAR NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (lesson_id, ordinal), \n\tFOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_audio_sources_lesson_id ON audio_sources (lesson_id)")
    op.execute(
        "CREATE TABLE chat_turns (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tlesson_id VARCHAR NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (lesson_id, ordinal), \n\tFOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_chat_turns_lesson_id ON chat_turns (lesson_id)")
    op.execute(
        "CREATE TABLE questions (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tlesson_id VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_questions_lesson_id ON questions (lesson_id)")
    op.execute(
        "CREATE TABLE summary_versions (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tlesson_id VARCHAR NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (lesson_id, version), \n\tFOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_summary_versions_lesson_id ON summary_versions (lesson_id)")
    op.execute(
        "CREATE TABLE answer_versions (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tquestion_id VARCHAR NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (question_id, version), \n\tFOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_answer_versions_question_id ON answer_versions (question_id)")
    op.execute(
        "CREATE TABLE audio_assets (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tsource_id VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(source_id) REFERENCES audio_sources (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_audio_assets_source_id ON audio_assets (source_id)")
    op.execute(
        "CREATE TABLE audio_chunks (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tsource_id VARCHAR NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (source_id, ordinal), \n\tFOREIGN KEY(source_id) REFERENCES audio_sources (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_audio_chunks_source_id ON audio_chunks (source_id)")
    op.execute(
        "CREATE TABLE chat_replies (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tturn_id VARCHAR NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (turn_id, version), \n\tFOREIGN KEY(turn_id) REFERENCES chat_turns (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_chat_replies_turn_id ON chat_replies (turn_id)")
    op.execute(
        "CREATE TABLE transcript_segments (\n\tid VARCHAR NOT NULL, \n\tdata JSON NOT NULL, \n\tlesson_id VARCHAR NOT NULL, \n\tsource_id VARCHAR NOT NULL, \n\tchunk_id VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (chunk_id), \n\tFOREIGN KEY(lesson_id) REFERENCES lessons (id) ON DELETE CASCADE, \n\tFOREIGN KEY(source_id) REFERENCES audio_sources (id) ON DELETE CASCADE, \n\tFOREIGN KEY(chunk_id) REFERENCES audio_chunks (id) ON DELETE CASCADE\n)"
    )
    op.execute("CREATE INDEX ix_transcript_segments_chunk_id ON transcript_segments (chunk_id)")
    op.execute("CREATE INDEX ix_transcript_segments_lesson_id ON transcript_segments (lesson_id)")
    op.execute("CREATE INDEX ix_transcript_segments_source_id ON transcript_segments (source_id)")
    op.execute(
        "CREATE TABLE question_segments (\n\tquestion_id VARCHAR NOT NULL, \n\tsegment_id VARCHAR NOT NULL, \n\tPRIMARY KEY (question_id, segment_id), \n\tFOREIGN KEY(question_id) REFERENCES questions (id) ON DELETE CASCADE, \n\tFOREIGN KEY(segment_id) REFERENCES transcript_segments (id) ON DELETE CASCADE\n)"
    )


def downgrade():
    op.execute("DROP TABLE question_segments")
    op.execute("DROP TABLE transcript_segments")
    op.execute("DROP TABLE chat_replies")
    op.execute("DROP TABLE audio_chunks")
    op.execute("DROP TABLE audio_assets")
    op.execute("DROP TABLE answer_versions")
    op.execute("DROP TABLE summary_versions")
    op.execute("DROP TABLE questions")
    op.execute("DROP TABLE chat_turns")
    op.execute("DROP TABLE audio_sources")
    op.execute("DROP TABLE lessons")
    op.execute("DROP TABLE settings")
    op.execute("DROP TABLE jobs")
    op.execute("DROP TABLE idempotency_keys")
    op.execute("DROP TABLE events")
    op.execute("DROP TABLE credentials")
    op.execute("DROP TABLE courses")
