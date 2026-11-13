"""Generate an atomic, collision-checking append for Rails API current/history tables.

The SQL is executed only by the guarded operator command against an exact Docker
container and database. All staging files are local to that container. No table
is truncated, updated, deleted, or restored.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

COPY_COLUMNS = {
    "nodes": "id,latitude,longitude,changeset_id,visible,timestamp,tile,version",
    "node_tags": "node_id,k,v",
    "ways": "id,changeset_id,timestamp,visible,version",
    "way_nodes": "way_id,node_id,sequence_id",
    "way_tags": "way_id,k,v",
    "relations": "id,changeset_id,timestamp,visible,version",
    "relation_members": "relation_id,member_type,member_id,member_role,sequence_id",
    "relation_tags": "relation_id,k,v",
}


def render(stage_directory: str):
    if not re.fullmatch(r"/tmp/brazil-stage-[a-z0-9-]+", stage_directory):
        raise ValueError("stage directory must be an exact safe /tmp path")
    lines = [
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        "SET LOCAL search_path = public, pg_temp;",
        "SET LOCAL TIME ZONE 'UTC';",
        "SET LOCAL statement_timeout = '15min';",
        "SET LOCAL lock_timeout = '30s';",
        "DO $$ BEGIN IF current_database() <> 'openstreetmap' OR NOT EXISTS (SELECT 1 FROM changesets WHERE id=0 AND user_id=-1) THEN RAISE EXCEPTION 'wrong database or anonymous import changeset'; END IF; END $$;",
        "LOCK TABLE current_nodes, current_ways, current_relations IN SHARE ROW EXCLUSIVE MODE;",
    ]
    for table, columns in COPY_COLUMNS.items():
        live_table = {
            "nodes": "current_nodes", "ways": "current_ways",
            "relations": "current_relations",
        }.get(table, "current_" + table)
        lines += [f"CREATE TEMP TABLE st_{table} (LIKE {live_table}) ON COMMIT PRESERVE ROWS;",
                  f"COPY st_{table} ({columns}) FROM '{stage_directory}/{table}.tsv' WITH (FORMAT csv, DELIMITER E'\\t', NULL '\\N');"]
    lines += [
        "CREATE UNIQUE INDEX ON st_nodes(id);",
        "CREATE UNIQUE INDEX ON st_ways(id);",
        "CREATE UNIQUE INDEX ON st_relations(id);",
        "CREATE INDEX ON st_node_tags(node_id);",
        "CREATE INDEX ON st_way_nodes(way_id);",
        "CREATE INDEX ON st_way_tags(way_id);",
        "CREATE INDEX ON st_relation_members(relation_id);",
        "CREATE INDEX ON st_relation_tags(relation_id);",
        "ANALYZE st_nodes; ANALYZE st_ways; ANALYZE st_relations;",
    ]
    lines += [
        "DO $$ DECLARE problem text; BEGIN",
        "IF EXISTS (SELECT 1 FROM st_nodes GROUP BY id HAVING count(*)>1) OR EXISTS (SELECT 1 FROM st_ways GROUP BY id HAVING count(*)>1) OR EXISTS (SELECT 1 FROM st_relations GROUP BY id HAVING count(*)>1) THEN RAISE EXCEPTION 'duplicate object IDs inside city stage'; END IF;",
        "IF EXISTS (SELECT 1 FROM st_way_nodes m WHERE NOT EXISTS (SELECT 1 FROM st_nodes n WHERE n.id=m.node_id) AND NOT EXISTS (SELECT 1 FROM current_nodes n WHERE n.id=m.node_id)) THEN RAISE EXCEPTION 'unresolved way-node reference'; END IF;",
        "IF EXISTS (SELECT 1 FROM st_relation_members m WHERE (m.member_type='Node' AND NOT EXISTS (SELECT 1 FROM st_nodes n WHERE n.id=m.member_id) AND NOT EXISTS (SELECT 1 FROM current_nodes n WHERE n.id=m.member_id)) OR (m.member_type='Way' AND NOT EXISTS (SELECT 1 FROM st_ways w WHERE w.id=m.member_id) AND NOT EXISTS (SELECT 1 FROM current_ways w WHERE w.id=m.member_id)) OR (m.member_type='Relation' AND NOT EXISTS (SELECT 1 FROM st_relations r WHERE r.id=m.member_id) AND NOT EXISTS (SELECT 1 FROM current_relations r WHERE r.id=m.member_id))) THEN RAISE EXCEPTION 'unresolved relation-member reference'; END IF;",
        "IF EXISTS (SELECT 1 FROM st_nodes s JOIN current_nodes c USING(id) WHERE to_jsonb(s) <> to_jsonb(c) OR (SELECT jsonb_object_agg(k,v) FROM st_node_tags t WHERE t.node_id=s.id) IS DISTINCT FROM (SELECT jsonb_object_agg(k,v) FROM current_node_tags t WHERE t.node_id=c.id)) THEN RAISE EXCEPTION 'node ID/version/content collision'; END IF;",
        "IF EXISTS (SELECT 1 FROM st_ways s JOIN current_ways c USING(id) WHERE to_jsonb(s) <> to_jsonb(c) OR (SELECT jsonb_object_agg(k,v) FROM st_way_tags t WHERE t.way_id=s.id) IS DISTINCT FROM (SELECT jsonb_object_agg(k,v) FROM current_way_tags t WHERE t.way_id=c.id) OR (SELECT jsonb_agg(jsonb_build_array(node_id,sequence_id) ORDER BY sequence_id) FROM st_way_nodes t WHERE t.way_id=s.id) IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array(node_id,sequence_id) ORDER BY sequence_id) FROM current_way_nodes t WHERE t.way_id=c.id)) THEN RAISE EXCEPTION 'way ID/version/content collision'; END IF;",
        "IF EXISTS (SELECT 1 FROM st_relations s JOIN current_relations c USING(id) WHERE to_jsonb(s) <> to_jsonb(c) OR (SELECT jsonb_object_agg(k,v) FROM st_relation_tags t WHERE t.relation_id=s.id) IS DISTINCT FROM (SELECT jsonb_object_agg(k,v) FROM current_relation_tags t WHERE t.relation_id=c.id) OR (SELECT jsonb_agg(jsonb_build_array(member_type::text,member_id,member_role,sequence_id) ORDER BY sequence_id) FROM st_relation_members t WHERE t.relation_id=s.id) IS DISTINCT FROM (SELECT jsonb_agg(jsonb_build_array(member_type::text,member_id,member_role,sequence_id) ORDER BY sequence_id) FROM current_relation_members t WHERE t.relation_id=c.id)) THEN RAISE EXCEPTION 'relation ID/version/content collision'; END IF;",
        "IF EXISTS (SELECT 1 FROM st_nodes s JOIN current_nodes c USING(id) LEFT JOIN nodes h ON h.node_id=c.id AND h.version=c.version WHERE h.node_id IS NULL) OR EXISTS (SELECT 1 FROM st_ways s JOIN current_ways c USING(id) LEFT JOIN ways h ON h.way_id=c.id AND h.version=c.version WHERE h.way_id IS NULL) OR EXISTS (SELECT 1 FROM st_relations s JOIN current_relations c USING(id) LEFT JOIN relations h ON h.relation_id=c.id AND h.version=c.version WHERE h.relation_id IS NULL) THEN RAISE EXCEPTION 'existing current object lacks matching history'; END IF;",
        "END $$;",
        "CREATE TEMP TABLE new_nodes AS SELECT s.* FROM st_nodes s WHERE NOT EXISTS (SELECT 1 FROM current_nodes c WHERE c.id=s.id);",
        "CREATE TEMP TABLE new_ways AS SELECT s.* FROM st_ways s WHERE NOT EXISTS (SELECT 1 FROM current_ways c WHERE c.id=s.id);",
        "CREATE TEMP TABLE new_relations AS SELECT s.* FROM st_relations s WHERE NOT EXISTS (SELECT 1 FROM current_relations c WHERE c.id=s.id);",
        "CREATE UNIQUE INDEX ON new_nodes(id);",
        "CREATE UNIQUE INDEX ON new_ways(id);",
        "CREATE UNIQUE INDEX ON new_relations(id);",
        "ANALYZE new_nodes; ANALYZE new_ways; ANALYZE new_relations;",
        "CREATE TEMP TABLE st_features AS SELECT DISTINCT metric,kind,id FROM (SELECT 'buildings' metric,'n' kind,node_id id FROM st_node_tags WHERE k='building' AND v<>'no' UNION ALL SELECT 'buildings','w',way_id FROM st_way_tags WHERE k='building' AND v<>'no' UNION ALL SELECT 'buildings','r',relation_id FROM st_relation_tags WHERE k='building' AND v<>'no' UNION ALL SELECT 'addresses','n',node_id FROM st_node_tags WHERE k LIKE 'addr:%' UNION ALL SELECT 'addresses','w',way_id FROM st_way_tags WHERE k LIKE 'addr:%' UNION ALL SELECT 'addresses','r',relation_id FROM st_relation_tags WHERE k LIKE 'addr:%' UNION ALL SELECT 'highway_ways','w',way_id FROM st_way_tags WHERE k='highway' AND v<>'no' UNION ALL SELECT 'other_features','n',node_id FROM st_node_tags WHERE k IN ('amenity','shop','landuse','natural','waterway','railway') UNION ALL SELECT 'other_features','w',way_id FROM st_way_tags WHERE k IN ('amenity','shop','landuse','natural','waterway','railway') UNION ALL SELECT 'other_features','r',relation_id FROM st_relation_tags WHERE k IN ('amenity','shop','landuse','natural','waterway','railway')) f;",
        "CREATE TEMP TABLE st_feature_status AS SELECT f.metric, CASE WHEN f.kind='n' THEN EXISTS (SELECT 1 FROM new_nodes n WHERE n.id=f.id) WHEN f.kind='w' THEN EXISTS (SELECT 1 FROM new_ways w WHERE w.id=f.id) ELSE EXISTS (SELECT 1 FROM new_relations r WHERE r.id=f.id) END AS inserted FROM st_features f;",
        "INSERT INTO current_nodes (id,latitude,longitude,changeset_id,visible,timestamp,tile,version) SELECT id,latitude,longitude,changeset_id,visible,timestamp,tile,version FROM new_nodes;",
        "INSERT INTO nodes (node_id,latitude,longitude,changeset_id,visible,timestamp,tile,version) SELECT id,latitude,longitude,changeset_id,visible,timestamp,tile,version FROM new_nodes;",
        "INSERT INTO current_node_tags (node_id,k,v) SELECT t.node_id,t.k,t.v FROM st_node_tags t JOIN new_nodes n ON n.id=t.node_id;",
        "INSERT INTO node_tags (node_id,version,k,v) SELECT t.node_id,n.version,t.k,t.v FROM st_node_tags t JOIN new_nodes n ON n.id=t.node_id;",
        "INSERT INTO current_ways (id,changeset_id,timestamp,visible,version) SELECT id,changeset_id,timestamp,visible,version FROM new_ways;",
        "INSERT INTO ways (way_id,changeset_id,timestamp,visible,version) SELECT id,changeset_id,timestamp,visible,version FROM new_ways;",
        "INSERT INTO current_way_nodes (way_id,node_id,sequence_id) SELECT t.way_id,t.node_id,t.sequence_id FROM st_way_nodes t JOIN new_ways w ON w.id=t.way_id;",
        "INSERT INTO way_nodes (way_id,node_id,version,sequence_id) SELECT t.way_id,t.node_id,w.version,t.sequence_id FROM st_way_nodes t JOIN new_ways w ON w.id=t.way_id;",
        "INSERT INTO current_way_tags (way_id,k,v) SELECT t.way_id,t.k,t.v FROM st_way_tags t JOIN new_ways w ON w.id=t.way_id;",
        "INSERT INTO way_tags (way_id,version,k,v) SELECT t.way_id,w.version,t.k,t.v FROM st_way_tags t JOIN new_ways w ON w.id=t.way_id;",
        "INSERT INTO current_relations (id,changeset_id,timestamp,visible,version) SELECT id,changeset_id,timestamp,visible,version FROM new_relations;",
        "INSERT INTO relations (relation_id,changeset_id,timestamp,visible,version) SELECT id,changeset_id,timestamp,visible,version FROM new_relations;",
        "INSERT INTO current_relation_members (relation_id,member_type,member_id,member_role,sequence_id) SELECT t.relation_id,t.member_type,t.member_id,t.member_role,t.sequence_id FROM st_relation_members t JOIN new_relations r ON r.id=t.relation_id;",
        "INSERT INTO relation_members (relation_id,member_type,member_id,member_role,version,sequence_id) SELECT t.relation_id,t.member_type,t.member_id,t.member_role,r.version,t.sequence_id FROM st_relation_members t JOIN new_relations r ON r.id=t.relation_id;",
        "INSERT INTO current_relation_tags (relation_id,k,v) SELECT t.relation_id,t.k,t.v FROM st_relation_tags t JOIN new_relations r ON r.id=t.relation_id;",
        "INSERT INTO relation_tags (relation_id,version,k,v) SELECT t.relation_id,r.version,t.k,t.v FROM st_relation_tags t JOIN new_relations r ON r.id=t.relation_id;",
        "SELECT setval('current_nodes_id_seq', GREATEST((SELECT max(id) FROM current_nodes),(SELECT last_value FROM current_nodes_id_seq)), true);",
        "SELECT setval('current_ways_id_seq', GREATEST((SELECT max(id) FROM current_ways),(SELECT last_value FROM current_ways_id_seq)), true);",
        "SELECT setval('current_relations_id_seq', GREATEST((SELECT max(id) FROM current_relations),(SELECT last_value FROM current_relations_id_seq)), true);",
        "COMMIT;",
        "SELECT 'IMPORT_AUDIT=' || json_build_object('nodes',json_build_object('source_retained', (SELECT count(*) FROM st_nodes),'existing_before',(SELECT count(*) FROM st_nodes)-(SELECT count(*) FROM new_nodes),'newly_inserted',(SELECT count(*) FROM new_nodes)), 'ways',json_build_object('source_retained',(SELECT count(*) FROM st_ways),'existing_before',(SELECT count(*) FROM st_ways)-(SELECT count(*) FROM new_ways),'newly_inserted',(SELECT count(*) FROM new_ways)), 'relations',json_build_object('source_retained',(SELECT count(*) FROM st_relations),'existing_before',(SELECT count(*) FROM st_relations)-(SELECT count(*) FROM new_relations),'newly_inserted',(SELECT count(*) FROM new_relations)), 'features',(SELECT json_object_agg(metric,json_build_object('source_retained',total,'existing_before',total-inserted,'newly_inserted',inserted)) FROM (SELECT metric,count(*) total,count(*) FILTER (WHERE inserted) inserted FROM st_feature_status GROUP BY metric) f), 'database_size_after',pg_database_size(current_database()))::text;",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage_directory")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(render(args.stage_directory))


if __name__ == "__main__":
    main()
