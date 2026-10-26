-- Patent citation flow between CPC technology fields.
-- Citing side: US grants (kind A before 2001, B1 and B2 from 2001) from 1985 to 2024.
-- Cited side: any publication in the table that has a CPC code.
-- Each publication maps to its first (primary) CPC code.
-- The output has two row types:
--   level 'X': citing 4-char class x cited 3-char subclass x year, complete.
--   level 'C': citing 4-char class x cited 4-char class x year, only pairs with 20 or more citations.
WITH cited AS (
  SELECT publication_number,
    COALESCE((SELECT c.code FROM UNNEST(cpc) c WHERE c.first LIMIT 1), cpc[SAFE_OFFSET(0)].code) AS cpc0
  FROM `patents-public-data.patents.publications`
  WHERE ARRAY_LENGTH(cpc) > 0
),
citing AS (
  SELECT CAST(FLOOR(p.publication_date/10000) AS INT64) AS yr,
    COALESCE((SELECT c.code FROM UNNEST(p.cpc) c WHERE c.first LIMIT 1), p.cpc[SAFE_OFFSET(0)].code) AS cpc0,
    cit.publication_number AS cited_pn
  FROM `patents-public-data.patents.publications` p, UNNEST(p.citation) cit
  WHERE p.country_code = 'US' AND p.kind_code IN ('A', 'B1', 'B2')
    AND p.publication_date BETWEEN 19850101 AND 20241231
    AND ARRAY_LENGTH(p.cpc) > 0 AND cit.publication_number IS NOT NULL AND cit.publication_number != ''
),
pairs AS (
  SELECT a.yr, SUBSTR(a.cpc0, 1, 4) AS citing_class, SUBSTR(b.cpc0, 1, 4) AS cited_class, COUNT(*) AS n
  FROM citing a JOIN cited b ON a.cited_pn = b.publication_number
  WHERE a.cpc0 IS NOT NULL AND b.cpc0 IS NOT NULL
  GROUP BY 1, 2, 3
)
SELECT 'X' AS level, yr, citing_class AS src, SUBSTR(cited_class, 1, 3) AS dst, SUM(n) AS n
FROM pairs GROUP BY 1, 2, 3, 4
UNION ALL
SELECT 'C' AS level, yr, citing_class AS src, cited_class AS dst, n
FROM pairs WHERE n >= 20
ORDER BY level, yr, src, dst
