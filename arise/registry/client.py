from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any

from arise.registry.models import RegistryEntry
from arise.types import Skill, SkillOrigin


def _entry_to_dict(entry: RegistryEntry) -> dict:
    return {
        "name": entry.name,
        "description": entry.description,
        "implementation": entry.implementation,
        "test_suite": entry.test_suite,
        "version": entry.version,
        "author": entry.author,
        "downloads": entry.downloads,
        "avg_success_rate": entry.avg_success_rate,
        "tags": entry.tags,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _dict_to_entry(d: dict) -> RegistryEntry:
    return RegistryEntry(
        name=d["name"],
        description=d.get("description", ""),
        implementation=d["implementation"],
        test_suite=d.get("test_suite", ""),
        version=d.get("version", 1),
        author=d.get("author", ""),
        downloads=d.get("downloads", 0),
        avg_success_rate=d.get("avg_success_rate", 0.0),
        tags=d.get("tags", []),
        created_at=datetime.fromisoformat(d["created_at"]) if d.get("created_at") else datetime.now(),
        updated_at=datetime.fromisoformat(d["updated_at"]) if d.get("updated_at") else datetime.now(),
    )


def _skill_from_entry(entry: RegistryEntry) -> Skill:
    return Skill(
        name=entry.name,
        description=entry.description,
        implementation=entry.implementation,
        test_suite=entry.test_suite,
        version=entry.version,
        origin=SkillOrigin.SYNTHESIZED,
    )


class SkillRegistry:
    """S3-backed skill registry for sharing evolved tools across projects.

    S3 layout:
        s3://{bucket}/{prefix}/index.json               {"skills": {"name": [versions]}}
        s3://{bucket}/{prefix}/skills/{name}/v{N}.json  RegistryEntry JSON
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "arise-registry",
        region: str = "us-east-1",
        s3_client: Any | None = None,
    ):
        self._bucket = bucket
        self._prefix = prefix.rstrip("/")

        if s3_client is not None:
            self._s3 = s3_client
        else:
            import boto3
            self._s3 = boto3.client("s3", region_name=region)

    # --- Index helpers ---

    def _index_key(self) -> str:
        return f"{self._prefix}/index.json"

    def _entry_key(self, name: str, version: int) -> str:
        return f"{self._prefix}/skills/{name}/v{version}.json"

    def _read_index(self) -> dict:
        """Read the registry index. Returns {"skills": {name: [versions]}}."""
        key = self._index_key()
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=key)
            return json.loads(resp["Body"].read())
        except Exception:
            return {"skills": {}}

    def _write_index(self, index: dict) -> None:
        key = self._index_key()
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(index),
            ContentType="application/json",
        )

    def _read_entry(self, name: str, version: int) -> RegistryEntry | None:
        key = self._entry_key(name, version)
        try:
            resp = self._s3.get_object(Bucket=self._bucket, Key=key)
            data = json.loads(resp["Body"].read())
            return _dict_to_entry(data)
        except Exception:
            return None

    def _write_entry(self, entry: RegistryEntry) -> None:
        key = self._entry_key(entry.name, entry.version)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=json.dumps(_entry_to_dict(entry)),
            ContentType="application/json",
        )

    # --- Public API ---

    def publish(self, skill: Skill, tags: list[str] | None = None) -> RegistryEntry:
        """Publish a skill to the registry. Writes skill JSON + updates index."""
        index = self._read_index()
        skills_map: dict[str, list[int]] = index.get("skills", {})

        existing_versions: list[int] = skills_map.get(skill.name, [])
        new_version = (max(existing_versions) + 1) if existing_versions else 1

        entry = RegistryEntry(
            name=skill.name,
            description=skill.description,
            implementation=skill.implementation,
            test_suite=skill.test_suite,
            version=new_version,
            tags=tags or [],
        )

        self._write_entry(entry)

        if skill.name not in skills_map:
            skills_map[skill.name] = []
        if new_version not in skills_map[skill.name]:
            skills_map[skill.name].append(new_version)
        index["skills"] = skills_map
        self._write_index(index)

        print(f"[ARISE:registry] Published '{skill.name}' v{new_version}", flush=True)
        return entry

    def search(self, query: str, limit: int = 10) -> list[RegistryEntry]:
        """Search registry by keyword matching on name + description + tags."""
        index = self._read_index()
        skills_map: dict[str, list[int]] = index.get("skills", {})

        if not skills_map:
            return []

        query_lower = query.lower()
        query_words = set(query_lower.split())

        results: list[tuple[int, RegistryEntry]] = []
        for name, versions in skills_map.items():
            if not versions:
                continue
            latest_version = max(versions)
            entry = self._read_entry(name, latest_version)
            if entry is None:
                continue

            # Score by keyword overlap
            score = 0
            text_lower = f"{entry.name} {entry.description} {' '.join(entry.tags)}".lower()
            for word in query_words:
                if word in text_lower:
                    score += 1

            if score > 0:
                results.append((score, entry))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in results[:limit]]

    def pull(self, name: str, version: int | None = None) -> Skill:
        """Pull a skill from registry and return as Skill object."""
        index = self._read_index()
        skills_map: dict[str, list[int]] = index.get("skills", {})

        if name not in skills_map or not skills_map[name]:
            raise ValueError(f"Skill '{name}' not found in registry")

        if version is None:
            version = max(skills_map[name])

        entry = self._read_entry(name, version)
        if entry is None:
            raise ValueError(f"Skill '{name}' v{version} not found in registry")

        # Increment downloads
        entry.downloads += 1
        self._write_entry(entry)

        print(f"[ARISE:registry] Pulled '{name}' v{version}", flush=True)
        return _skill_from_entry(entry)
