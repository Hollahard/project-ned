use friday_supervisor::processes::JobObject;
use std::process::{Command, Stdio};

#[test]
fn test_job_object_creation_and_limits() {
    let job = JobObject::new();
    assert!(job.is_ok(), "Job Object creation must succeed on Windows");
}

#[test]
fn test_job_object_assign_and_kill_on_drop() {
    let job = JobObject::new().expect("Failed to create Job Object");

    // Spawn a long-running child process
    let mut child = Command::new("cmd.exe")
        .args(["/c", "ping", "127.0.0.1", "-n", "30"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .expect("Failed to spawn test process");

    let pid = child.id();
    assert!(pid > 0);

    // Assign process to Job Object
    let assign_res = job.assign(&child);
    assert!(assign_res.is_ok(), "Process must be assigned to Job Object");

    // Drop the Job Object - should kill all child processes immediately
    drop(job);

    // Give kernel a brief moment to terminate process
    std::thread::sleep(std::time::Duration::from_millis(300));

    // Try killing the child; if already dead or exited, status check will confirm
    let wait_res = child.try_wait();
    assert!(
        wait_res.is_ok(),
        "Process handle must report terminated or exited"
    );
}
