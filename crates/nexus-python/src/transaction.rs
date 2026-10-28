//! Transaction orchestration. The Python adapter retains the existing safe IO.
//! A callback returning successfully is not an independent durability proof.

use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

fn set_phase(state: &Bound<'_, PyDict>, phase: &str) -> PyResult<()> {
    state.set_item("phase", phase)
}

fn checkpoint(io: &Bound<'_, PyAny>, phase: &str) -> PyResult<()> {
    io.call_method1("checkpoint", (phase,))?;
    Ok(())
}

fn inventory<'py>(state: &Bound<'py, PyDict>) -> PyResult<Bound<'py, PyList>> {
    state
        .get_item("files")?
        .ok_or_else(|| PyValueError::new_err("Missing transaction inventory"))?
        .cast_into::<PyList>()
        .map_err(Into::into)
}

fn recover(io: &Bound<'_, PyAny>) -> PyResult<()> {
    let state = io.call_method0("load_journal")?;
    if state.is_none() {
        io.call_method0("cleanup_orphan")?;
        return Ok(());
    }
    let state = state.cast::<PyDict>()?;
    let phase: String = state
        .get_item("phase")?
        .ok_or_else(|| PyValueError::new_err("Missing transaction phase"))?
        .extract()?;
    let items = inventory(state)?;
    match phase.as_str() {
        "prepared" => {
            // Complete preflight before the first restoration/deletion.
            for (index, item) in items.iter().enumerate() {
                io.call_method1("check_backup", (index, &item))?;
            }
            for (index, item) in items.iter().enumerate() {
                io.call_method1("restore", (index, &item))?;
            }
        }
        "preparing" | "committed" => {}
        _ => return Err(PyValueError::new_err("Invalid file transaction journal")),
    }
    // Persist this only after restoration is complete. Partial rollback keeps
    // the prepared journal, so recovery can repeat after interruption.
    set_phase(state, "committed")?;
    io.call_method1("write_journal", (state,))?;
    checkpoint(io, "cleanup")?;
    io.call_method0("cleanup")?;
    Ok(())
}

#[pyfunction]
pub fn transaction_recover(io: &Bound<'_, PyAny>) -> PyResult<()> {
    recover(io)
}

#[pyfunction]
pub fn transaction_apply(io: &Bound<'_, PyAny>) -> PyResult<()> {
    io.call_method0("validate_state_path")?;
    recover(io)?;
    let state = io.call_method0("prepare")?.cast_into::<PyDict>()?;
    io.call_method1("write_journal", (&state,))?;
    checkpoint(io, "preparing")?;
    let result = (|| -> PyResult<()> {
        let items = inventory(&state)?;
        for (index, item) in items.iter().enumerate() {
            io.call_method1("backup", (index, &item))?;
            checkpoint(io, "backup")?;
        }
        set_phase(&state, "prepared")?;
        io.call_method1("write_journal", (&state,))?;
        checkpoint(io, "prepared")?;
        let records = io.getattr("records")?.try_iter()?;
        for record in records {
            let record = record?;
            io.call_method1("replace", (&record,))?;
            checkpoint(io, "replace")?;
        }
        let removed = io.getattr("removed")?.try_iter()?;
        for path in removed {
            let path = path?;
            io.call_method1("delete", (&path,))?;
        }
        io.call_method0("write_state")?;
        checkpoint(io, "state")?;
        set_phase(&state, "committed")?;
        io.call_method1("write_journal", (&state,))?;
        checkpoint(io, "committed")?;
        Ok(())
    })();
    if let Err(error) = result {
        // Preserve Python's `except Exception`, not `except BaseException`:
        // process interruption must not be converted into claimed completion.
        if error.is_instance_of::<PyException>(io.py())
            && let Err(recovery_error) = recover(io)
        {
            recovery_error.set_context(io.py(), Some(error));
            return Err(recovery_error);
        }
        return Err(error);
    }
    recover(io)
}
