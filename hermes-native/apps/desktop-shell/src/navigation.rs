//! A fence for an owned preview context. Call only for an allowed main-document
//! navigation, after rejecting remote URLs and unexpected bundled paths.

use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Default)]
pub struct PreviewNavigationFence {
    initial_seen: AtomicBool,
    retirement_requested: AtomicBool,
}

impl PreviewNavigationFence {
    /// False for the one initial allowed navigation. True thereafter: retire
    /// the existing PreviewState before this navigation callback returns.
    pub fn on_allowed_navigation(&self) -> bool {
        if self.initial_seen.swap(true, Ordering::AcqRel) {
            self.retirement_requested.store(true, Ordering::Release);
            true
        } else {
            false
        }
    }

    /// Check immediately after PreviewState is managed, covering a second
    /// document navigation that arrived before native setup stored the state.
    pub fn retirement_requested(&self) -> bool {
        self.retirement_requested.load(Ordering::Acquire)
    }
}

#[cfg(test)]
mod tests {
    use super::PreviewNavigationFence;

    #[test]
    fn first_navigation_is_live_later_navigation_is_permanently_retired() {
        let fence = PreviewNavigationFence::default();
        assert!(!fence.on_allowed_navigation());
        assert!(!fence.retirement_requested());
        assert!(fence.on_allowed_navigation());
        assert!(fence.retirement_requested());
        assert!(fence.on_allowed_navigation());
    }

    #[test]
    fn a_reload_before_owner_management_is_remembered() {
        let fence = PreviewNavigationFence::default();
        fence.on_allowed_navigation();
        fence.on_allowed_navigation();
        assert!(fence.retirement_requested());
    }
}
