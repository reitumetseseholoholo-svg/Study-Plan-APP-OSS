use pyo3::prelude::*;
use std::collections::HashSet;

#[pyfunction]
fn select_srs_from_scored(
    idxs: Vec<usize>,
    due: Vec<u8>,
    overdue: Vec<u8>,
    in_cooldown: Vec<u8>,
    recent: Vec<u8>,
    is_new: Vec<u8>,
    retention: Vec<f64>,
    risk: Vec<f64>,
    gap_bonus: Vec<f64>,
    count: usize,
    n_questions: usize,
    recent_set: Vec<usize>,
) -> Vec<usize> {
    let n = idxs.len();
    if n == 0 {
        return vec![];
    }
    let target = std::cmp::min(count, n_questions);
    if target == 0 {
        return vec![];
    }

    let recent_lookup: HashSet<usize> = recent_set.into_iter().collect();

    // Phase 1: due items first
    let mut due_indices: Vec<usize> = (0..n).filter(|&i| due[i] == 1).collect();
    due_indices.sort_by(|&a, &b| {
        in_cooldown[a]
            .cmp(&in_cooldown[b])
            .then(overdue[b].cmp(&overdue[a]))
            .then(
                gap_bonus[b]
                    .partial_cmp(&gap_bonus[a])
                    .unwrap_or(std::cmp::Ordering::Equal),
            )
            .then(
                risk[b]
                    .partial_cmp(&risk[a])
                    .unwrap_or(std::cmp::Ordering::Equal),
            )
            .then(
                retention[a]
                    .partial_cmp(&retention[b])
                    .unwrap_or(std::cmp::Ordering::Equal),
            )
    });
    let max_due = std::cmp::min(target, std::cmp::max(3, (count as f64 * 0.5) as usize));
    let mut selected: Vec<usize> =
        due_indices.iter().take(max_due).map(|&i| idxs[i]).collect();
    let due_count = due_indices.len();

    // Phase 2: fill from non-cooldown pool
    if selected.len() < target {
        let remaining = target - selected.len();
        let sel_set: HashSet<usize> = selected.iter().copied().collect();
        let mut pool: Vec<usize> = (0..n)
            .filter(|&i| due[i] == 0 && !sel_set.contains(&idxs[i]) && in_cooldown[i] == 0)
            .collect();
        pool.sort_by(|&a, &b| {
            overdue[b]
                .cmp(&overdue[a])
                .then(
                    gap_bonus[b]
                        .partial_cmp(&gap_bonus[a])
                        .unwrap_or(std::cmp::Ordering::Equal),
                )
                .then(
                    risk[b]
                        .partial_cmp(&risk[a])
                        .unwrap_or(std::cmp::Ordering::Equal),
                )
                .then(is_new[b].cmp(&is_new[a]))
                .then(recent[a].cmp(&recent[b]))
                .then(
                    retention[a]
                        .partial_cmp(&retention[b])
                        .unwrap_or(std::cmp::Ordering::Equal),
                )
        });
        for &i in pool.iter().take(remaining) {
            selected.push(idxs[i]);
        }
    }

    // Phase 3: fallback to cooldown items
    if selected.len() < target {
        let remaining = target - selected.len();
        let sel_set: HashSet<usize> = selected.iter().copied().collect();
        let mut fallback: Vec<usize> = (0..n)
            .filter(|&i| !sel_set.contains(&idxs[i]))
            .collect();
        fallback.sort_by(|&a, &b| {
            due[b]
                .cmp(&due[a])
                .then(overdue[b].cmp(&overdue[a]))
                .then(
                    gap_bonus[b]
                        .partial_cmp(&gap_bonus[a])
                        .unwrap_or(std::cmp::Ordering::Equal),
                )
                .then(
                    risk[b]
                        .partial_cmp(&risk[a])
                        .unwrap_or(std::cmp::Ordering::Equal),
                )
                .then(recent[a].cmp(&recent[b]))
                .then(
                    retention[a]
                        .partial_cmp(&retention[b])
                        .unwrap_or(std::cmp::Ordering::Equal),
                )
        });
        for &i in fallback.iter().take(remaining) {
            selected.push(idxs[i]);
        }
    }

    // Phase 4: diversity enforcement
    if !recent_lookup.is_empty() && target > 0 {
        let min_non_recent = (target as f64 * 0.70).ceil() as usize;
        let due_pressure = due_count >= std::cmp::max(1, (target as f64 * 0.60).ceil() as usize);
        if !due_pressure {
            let non_recent_selected: Vec<&usize> = selected
                .iter()
                .filter(|idx| !recent_lookup.contains(idx))
                .collect();
            if non_recent_selected.len() < min_non_recent {
                let needed = min_non_recent - non_recent_selected.len();
                let sel_set: HashSet<usize> = selected.iter().copied().collect();
                let mut candidates: Vec<usize> = (0..n)
                    .filter(|&i| !sel_set.contains(&idxs[i]) && recent[i] == 0)
                    .collect();
                candidates.sort_by(|&a, &b| {
                    due[b]
                        .cmp(&due[a])
                        .then(overdue[b].cmp(&overdue[a]))
                        .then(
                            gap_bonus[b]
                                .partial_cmp(&gap_bonus[a])
                                .unwrap_or(std::cmp::Ordering::Equal),
                        )
                        .then(
                            risk[b]
                                .partial_cmp(&risk[a])
                                .unwrap_or(std::cmp::Ordering::Equal),
                        )
                        .then(
                            retention[a]
                                .partial_cmp(&retention[b])
                                .unwrap_or(std::cmp::Ordering::Equal),
                        )
                });
                let additions: Vec<usize> = candidates.iter().take(needed).map(|&i| idxs[i]).collect();
                if !additions.is_empty() {
                    let replaceable: Vec<usize> = selected
                        .iter()
                        .filter(|&&idx| recent_lookup.contains(&idx) && {
                            let pos = idxs.iter().position(|&x| x == idx);
                            pos.map(|p| due[p] == 0).unwrap_or(false)
                        })
                        .copied()
                        .collect();
                    let mut replace_iter = replaceable.into_iter();
                    for &add_idx in &additions {
                        if let Some(old_idx) = replace_iter.next() {
                            if let Some(pos) = selected.iter().position(|&x| x == old_idx) {
                                selected[pos] = add_idx;
                            }
                        } else {
                            break;
                        }
                    }
                }
            }
        }
    }

    selected
}

#[pyfunction]
fn batch_score_srs(
    has_fsrs_due: Vec<u8>,
    fsrs_due_days_since: Vec<i32>,
    has_last_review: Vec<u8>,
    days_since_review: Vec<i32>,
    sm2_interval: Vec<f64>,
    has_fsrs_stability: Vec<u8>,
    fsrs_stability: Vec<f64>,
) -> (Vec<i32>, Vec<f64>) {
    let n = has_fsrs_due.len();
    let mut overdue = Vec::with_capacity(n);
    let mut retention = Vec::with_capacity(n);

    for i in 0..n {
        // ---- is_overdue ----
        let ov = if has_fsrs_due[i] != 0 && fsrs_due_days_since[i] >= 0 {
            1i32
        } else if has_last_review[i] == 0 {
            0i32
        } else {
            let interval = sm2_interval[i].max(1.0);
            if (days_since_review[i] as f64) >= interval { 1i32 } else { 0i32 }
        };
        overdue.push(ov);

        // ---- get_retention_probability ----
        let ret = if has_last_review[i] == 0 || days_since_review[i] < 0 {
            0.0
        } else {
            let ds = days_since_review[i] as f64;
            if has_fsrs_stability[i] != 0 && fsrs_stability[i] > 0.0 {
                let s = fsrs_stability[i].max(0.1);
                0.9f64.powf(ds / s)
            } else {
                let interval = sm2_interval[i].max(1.0);
                0.9f64.powf(ds / interval)
            }
        };
        retention.push(ret);
    }

    (overdue, retention)
}

#[pymodule]
fn studyplan_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(select_srs_from_scored, m)?)?;
    m.add_function(wrap_pyfunction!(batch_score_srs, m)?)?;
    Ok(())
}
