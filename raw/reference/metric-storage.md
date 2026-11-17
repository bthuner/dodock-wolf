# Metric storage

> How Wolf stores metrics at three resolutions, rolls them up, purges them and ingests pushes.

At 50 hosts × 15 metrics every 30 s, raw samples are about 2 M rows a day. Wolf therefore keeps
three resolutions, each with its own retention in **Wolf Settings → Retention**.

## Resolutions

<table>
<thead>
  <tr>
    <th>
      Resolution
    </th>
    
    <th>
      DocType
    </th>
    
    <th>
      Default retention
    </th>
    
    <th>
      Read by
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Raw samples
    </td>
    
    <td>
      Wolf Metric Sample
    </td>
    
    <td>
      48 hours
    </td>
    
    <td>
      Rule windows up to 3 h, the 1 h chart
    </td>
  </tr>
  
  <tr>
    <td>
      1-minute rollups
    </td>
    
    <td>
      Wolf Metric Rollup (<code>
        resolution
      </code>
      
       60)
    </td>
    
    <td>
      30 days
    </td>
    
    <td>
      Windows up to 2 days (6 h and 24 h charts)
    </td>
  </tr>
  
  <tr>
    <td>
      1-hour rollups
    </td>
    
    <td>
      Wolf Metric Rollup (<code>
        resolution
      </code>
      
       3600)
    </td>
    
    <td>
      365 days
    </td>
    
    <td>
      Longer windows (7 d chart)
    </td>
  </tr>
</tbody>
</table>

A rollup row stores, for one series (metric, host, bench, site, labels) in one bucket:

- count;
- sum;
- min;
- max;
- the last value, with its time.

So `avg`, `min`, `max`, `sum`, `count` and `last` over whole buckets equal the raw answer.

A read takes, in order:

1. the coarsest resolution allowed for its window, up to the last rolled bucket;
2. then finer rollups;
3. then the raw samples not rolled up yet, so the newest minutes are always there.

A long window loses at most one bucket at its start: under a minute for 1-minute reads, under an
hour for 1-hour reads.

## Rollups

The `rollup_metrics` job runs every minute.

- It rolls closed minutes, 2 minutes after they end, and closed hours.
- Its progress is in **Wolf Rollup State**.
- It recomputes whole buckets, so running it again never double counts.
- Samples that arrive late, for example an agent replaying its spool, move the progress back.
Their buckets are rolled again, up to the raw retention.

<tip>

Rollups, like alert rules, depend on the scheduler tick. Set `scheduler_tick_interval` to 60 (see
[Install the Wolf App](/install/wolf-app)).

</tip>

## Purge

`purge_metrics` runs hourly and applies the retention.

<note>

It never deletes raw samples or 1-minute rollups that are not rolled up yet.

</note>

Event retention (`event_retention_days`) is separate and unchanged by metric retention.

## Ingest mode

Set in **Wolf Settings → Agents → Ingest Mode**.

<table>
<thead>
  <tr>
    <th>
      Mode
    </th>
    
    <th>
      Behaviour
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      <code>
        async
      </code>
      
       (default)
    </td>
    
    <td>
      Validates a push, queues the inserts on the <code>
        short
      </code>
      
       queue and answers at once. A worker inserts the batch and attaches its events to open incidents. If the queue is unreachable, the push is stored inline.
    </td>
  </tr>
  
  <tr>
    <td>
      <code>
        sync
      </code>
    </td>
    
    <td>
      Stores during the request.
    </td>
  </tr>
</tbody>
</table>

In both modes, the agent's last seen time, clock skew and Wolf's health are updated during the
request. The answer an agent gets in each mode is in the
[protocol](/reference/protocol#ingest-mode).

## Performance

Metric rows are stored in metric and time order, and reads of known metrics scan the primary key
by name range. Measured results at 100 hosts × 7 days are in
[Performance](/reference/performance).

## Optional time-series backend

<warning>

Design only, **not built**.

</warning>

The read path goes through two functions:

- `rollups.aggregate()`, for rules;
- `rollups.series_rows()`, for charts.

Writes go through `events.insert_metrics()`.

A ClickHouse or TimescaleDB backend would implement those three:

<table>
<thead>
  <tr>
    <th>
      Part
    </th>
    
    <th>
      ClickHouse
    </th>
    
    <th>
      TimescaleDB
    </th>
  </tr>
</thead>

<tbody>
  <tr>
    <td>
      Raw samples
    </td>
    
    <td>
      A <code>
        MergeTree
      </code>
      
       table
    </td>
    
    <td>
      A hypertable
    </td>
  </tr>
  
  <tr>
    <td>
      Minute and hour rollups
    </td>
    
    <td>
      Materialized views (<code>
        AggregatingMergeTree
      </code>
      
       with <code>
        sumState/minState/maxState/argMaxState
      </code>
      
      )
    </td>
    
    <td>
      Continuous aggregates with <code>
        first/last
      </code>
    </td>
  </tr>
  
  <tr>
    <td>
      Retention
    </td>
    
    <td>
      TTL
    </td>
    
    <td>
      <code>
        add_retention_policy
      </code>
    </td>
  </tr>
</tbody>
</table>

The watermark logic and the purge job would then be the database's job. Until a site needs more
than a few hundred hosts, the Frappe tables above are enough and keep Wolf a plain Frappe app.
