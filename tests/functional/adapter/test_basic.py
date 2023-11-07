import pytest

import boto3
import os
from urllib.parse import urlparse
from dbt.tests.adapter.basic.test_base import BaseSimpleMaterializations
from dbt.tests.adapter.basic.test_singular_tests import BaseSingularTests
from dbt.tests.adapter.basic.test_singular_tests_ephemeral import BaseSingularTestsEphemeral
from dbt.tests.adapter.basic.test_empty import BaseEmpty
from dbt.tests.adapter.basic.test_ephemeral import BaseEphemeral
from dbt.tests.adapter.basic.test_incremental import BaseIncremental
from dbt.tests.adapter.basic.test_generic_tests import BaseGenericTests
from dbt.tests.adapter.basic.test_docs_generate import BaseDocsGenerate, BaseDocsGenReferences
from dbt.tests.adapter.basic.test_snapshot_check_cols import BaseSnapshotCheckCols
from dbt.tests.adapter.basic.test_snapshot_timestamp import BaseSnapshotTimestamp
from dbt.tests.adapter.basic.files import (
    base_view_sql,
    base_table_sql,
    base_ephemeral_sql,
    ephemeral_view_sql,
    ephemeral_table_sql,
)
from dbt.tests.util import (
    run_dbt,
    get_manifest,
    check_relations_equal,
    check_result_nodes_by_name,
    relation_from_name,
)
from tests.util import get_s3_location, get_region

s3bucket = get_s3_location()
region = get_region()
schema_name = "dbt_functional_test_01"

# override schema_base_yml to set missing database
schema_base_yml = """
version: 2
sources:
  - name: raw
    schema: "{{ target.schema }}"
    database: "{{ target.schema }}"
    tables:
      - name: seed
        identifier: "{{ var('seed_name', 'base') }}"
"""

# override base_materialized_var_sql to set strategy=insert_overwrite
config_materialized_var = """
  {{ config(materialized=var("materialized_var", "table")) }}
"""
config_incremental_strategy = """
  {{ config(incremental_strategy='insert_overwrite') }}
"""
model_base = """
  select * from {{ source('raw', 'seed') }}
"""
base_materialized_var_sql = config_materialized_var + config_incremental_strategy + model_base


def cleanup_s3_location():
    client = boto3.client("s3", region_name=region)
    S3Url(s3bucket + schema_name + "/base/").delete_all_keys_v2(client)
    S3Url(s3bucket + schema_name + "/table_model/").delete_all_keys_v2(client)
    S3Url(s3bucket + schema_name + "/added/").delete_all_keys_v2(client)
    S3Url(s3bucket + schema_name + "/swappable/").delete_all_keys_v2(client)


class TestSimpleMaterializationsGlue(BaseSimpleMaterializations):
    # all tests within this test has the same schema
    @pytest.fixture(scope="class")
    def unique_schema(request, prefix) -> str:
        return schema_name

    @pytest.fixture(scope="class")
    def models(self):
        return {
            "view_model.sql": base_view_sql,
            "table_model.sql": base_table_sql,
            "swappable.sql": base_materialized_var_sql,
            "schema.yml": schema_base_yml,
        }

    @pytest.fixture(scope='class', autouse=True)
    def cleanup(self):
        cleanup_s3_location()
        yield
        cleanup_s3_location()

    pass


class TestSingularTestsGlue(BaseSingularTests):
    @pytest.fixture(scope="class")
    def unique_schema(request, prefix) -> str:
        return schema_name

    @pytest.fixture(scope='class', autouse=True)
    def cleanup(self):
        cleanup_s3_location()
        yield
        cleanup_s3_location()

    pass


class TestEmptyGlue(BaseEmpty):
    @pytest.fixture(scope="class")
    def unique_schema(request, prefix) -> str:
        return schema_name

    @pytest.fixture(scope='class', autouse=True)
    def cleanup(self):
        cleanup_s3_location()
        yield
        cleanup_s3_location()

    pass


class TestEphemeralGlue(BaseEphemeral):
    # all tests within this test has the same schema
    @pytest.fixture(scope="class")
    def unique_schema(request, prefix) -> str:
        return schema_name

    @pytest.fixture(scope="class")
    def models(self):
        return {
            "ephemeral.sql": base_ephemeral_sql,
            "view_model.sql": ephemeral_view_sql,
            "table_model.sql": ephemeral_table_sql,
            "schema.yml": schema_base_yml,
        }

    @pytest.fixture(scope='class', autouse=True)
    def cleanup(self):
        cleanup_s3_location()
        yield
        cleanup_s3_location()

    def test_ephemeral(self, project):
        # seed command
        results = run_dbt(["seed"])
        assert len(results) == 1
        check_result_nodes_by_name(results, ["base"])

        # run command
        results = run_dbt(["run"])
        assert len(results) == 2
        check_result_nodes_by_name(results, ["view_model", "table_model"])

        # base table rowcount
        relation = relation_from_name(project.adapter, "base")
        # glue: run refresh table to disable the previous parquet file paths
        project.run_sql(f"refresh table {relation}")
        result = project.run_sql(f"select count(*) as num_rows from {relation}", fetch="one")
        assert result[0] == 10

        # glue: run refresh table to disable the previous parquet file paths
        relation = relation_from_name(project.adapter, "table_model")
        project.run_sql(f"refresh table {relation}")

        # relations equal
        check_relations_equal(project.adapter, ["base", "view_model", "table_model"])

        # catalog node count
        catalog = run_dbt(["docs", "generate"])
        catalog_path = os.path.join(project.project_root, "target", "catalog.json")
        assert os.path.exists(catalog_path)
        assert len(catalog.nodes) == 3
        assert len(catalog.sources) == 1

        # manifest (not in original)
        manifest = get_manifest(project.project_root)
        assert len(manifest.nodes) == 4
        assert len(manifest.sources) == 1

    pass

class TestSingularTestsEphemeralGlue(BaseSingularTestsEphemeral):
    @pytest.fixture(scope="class")
    def unique_schema(request, prefix) -> str:
        return schema_name

    @pytest.fixture(scope='class', autouse=True)
    def cleanup(self):
        cleanup_s3_location()
        yield
        cleanup_s3_location()

    pass

class TestIncrementalGlue(BaseIncremental):
    @pytest.fixture(scope='class', autouse=True)
    def cleanup(self):
        cleanup_s3_location()
        yield
        cleanup_s3_location()

    @pytest.fixture(scope="class")
    def models(self):
        model_incremental = """
           select * from {{ source('raw', 'seed') }}
           """.strip()

        return {"incremental.sql": model_incremental, "schema.yml": schema_base_yml}

    @pytest.fixture(scope="class")
    def unique_schema(request, prefix) -> str:
        return schema_name

    def test_incremental(self, project):
        # seed command
        results = run_dbt(["seed"])
        assert len(results) == 2

        # base table rowcount
        relation = relation_from_name(project.adapter, "base")
        # glue: run refresh table to disable the previous parquet file paths
        project.run_sql(f"refresh table {relation}")
        result = project.run_sql(f"select count(*) as num_rows from {relation}", fetch="one")
        assert result[0] == 10

        # added table rowcount
        relation = relation_from_name(project.adapter, "added")
        # glue: run refresh table to disable the previous parquet file paths
        project.run_sql(f"refresh table {relation}")
        result = project.run_sql(f"select count(*) as num_rows from {relation}", fetch="one")
        assert result[0] == 20

        # run command
        # the "seed_name" var changes the seed identifier in the schema file
        results = run_dbt(["run", "--vars", "seed_name: base"])
        assert len(results) == 1

        # check relations equal
        check_relations_equal(project.adapter, ["base", "incremental"])

        # change seed_name var
        # the "seed_name" var changes the seed identifier in the schema file
        results = run_dbt(["run", "--vars", "seed_name: added"])
        assert len(results) == 1

        # check relations equal
        check_relations_equal(project.adapter, ["added", "incremental"])

        # get catalog from docs generate
        catalog = run_dbt(["docs", "generate"])
        assert len(catalog.nodes) == 3
        assert len(catalog.sources) == 1

    pass


class TestGenericTestsGlue(BaseGenericTests):
    @pytest.fixture(scope="class")
    def unique_schema(request, prefix) -> str:
        return schema_name

    @pytest.fixture(scope='class', autouse=True)
    def cleanup(self):
        cleanup_s3_location()
        yield
        cleanup_s3_location()

    pass

# To test
#class TestDocsGenerate(BaseDocsGenerate):
#    pass


#class TestDocsGenReferences(BaseDocsGenReferences):
#    pass


# To Dev
#class TestSnapshotCheckColsGlue(BaseSnapshotCheckCols):
#    pass


#class TestSnapshotTimestampGlue(BaseSnapshotTimestamp):
#    pass

class S3Url(object):
    def __init__(self, url):
        self._parsed = urlparse(url, allow_fragments=False)

    @property
    def bucket(self):
        return self._parsed.netloc

    @property
    def key(self):
        if self._parsed.query:
            return self._parsed.path.lstrip("/") + "?" + self._parsed.query
        else:
            return self._parsed.path.lstrip("/")

    @property
    def url(self):
        return self._parsed.geturl()

    def delete_all_keys_v2(self, client):
        bucket = self.bucket
        prefix = self.key

        for response in client.get_paginator('list_objects_v2').paginate(Bucket=bucket, Prefix=prefix):
            if 'Contents' not in response:
                continue
            for content in response['Contents']:
                print("Deleting: s3://" + bucket + "/" + content['Key'])
                client.delete_object(Bucket=bucket, Key=content['Key'])
