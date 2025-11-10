/**
 * Fixed FollowButton React Component
 * 
 * KEY IMPROVEMENTS:
 * 1. Waits for HTTP 200 before committing to UI state (no blind optimistic update)
 * 2. Shows loading spinner during API call
 * 3. Rolls back UI on error
 * 4. Proper error handling and user feedback
 * 5. Integrates with tenant_id from context
 * 
 * ADDRESSES:
 * - delayed_backend_confirmation: waits for HTTP 200
 * - ui_desync_cache_delay: doesn't assume success until API confirms
 * - concurrent_toggle_race: prevents rapid clicks while loading
 */

import React, { useState, useEffect } from 'react';
import axios from 'axios';

/**
 * FollowButton Component
 * 
 * Props:
 *   - tenantId: current tenant ID (from auth context)
 *   - currentUserId: user ID of the logged-in user
 *   - targetUserId: user ID to follow/unfollow
 *   - onFollowChange: callback when follow state changes
 */
function FollowButton({ tenantId, currentUserId, targetUserId, onFollowChange }) {
  const [isFollowing, setIsFollowing] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  
  // Initial fetch to determine current state
  useEffect(() => {
    fetchFollowStatus();
  }, [tenantId, currentUserId, targetUserId]);
  
  /**
   * Fetch current follow status from API
   * This is the source of truth - we never trust local state without confirmation
   */
  async function fetchFollowStatus() {
    try {
      setIsLoading(true);
      setError(null);
      
      // KEY FIX: Include tenant_id in request to ensure isolation
      const response = await axios.get(
        `/api/follow_status/${tenantId}/${currentUserId}/${targetUserId}`,
        { timeout: 5000 } // 5 second timeout
      );
      
      // Extract following state from response
      const following = response.data.following;
      setIsFollowing(following);
      console.log(`[FollowButton] Status fetched: tenant=${tenantId}, current=${currentUserId}, target=${targetUserId}, following=${following}`);
      
    } catch (err) {
      console.error('[FollowButton] Error fetching follow status:', err);
      setError('Failed to load follow status');
      // On error, assume not following (conservative approach)
      setIsFollowing(false);
    } finally {
      setIsLoading(false);
    }
  }
  
  /**
   * Handle follow button click
   * KEY IMPROVEMENTS:
   * 1. Prevent rapid clicks with isLoading flag
   * 2. Show loading state to user
   * 3. Wait for HTTP 200 before updating UI
   * 4. Rollback on error
   * 5. Inform user of errors
   */
  async function handleFollowClick() {
    if (isLoading || isFollowing === null) {
      return; // Prevent clicking while loading or state unknown
    }
    
    const previousState = isFollowing;
    
    try {
      setIsLoading(true);
      setError(null);
      
      if (isFollowing) {
        // KEY FIX: Unfollow - wait for confirmation
        console.log(`[FollowButton] Initiating unfollow...`);
        const response = await axios.delete(
          `/api/follow/${tenantId}/${currentUserId}/${targetUserId}`,
          { timeout: 10000 }
        );
        
        // KEY FIX: Only update UI on 200 status
        if (response.status === 200) {
          setIsFollowing(false);
          console.log(`[FollowButton] Unfollow successful`);
          if (onFollowChange) onFollowChange(false);
        }
      } else {
        // KEY FIX: Follow - wait for confirmation
        console.log(`[FollowButton] Initiating follow...`);
        const response = await axios.post(
          `/api/follow/${tenantId}/${currentUserId}/${targetUserId}`,
          {},
          { timeout: 10000 }
        );
        
        // KEY FIX: Only update UI on 200 status
        if (response.status === 200) {
          setIsFollowing(true);
          console.log(`[FollowButton] Follow successful`);
          if (onFollowChange) onFollowChange(true);
        }
      }
      
    } catch (err) {
      console.error('[FollowButton] Error during follow action:', err);
      
      // KEY FIX: Rollback UI on error
      setIsFollowing(previousState);
      
      // Set user-friendly error message
      if (err.response?.status === 400) {
        setError('Invalid request. Please refresh and try again.');
      } else if (err.response?.status === 409) {
        setError('Conflicting operation. Please refresh.');
      } else if (err.response?.status === 500) {
        setError('Server error. Please try again later.');
      } else if (err.code === 'ECONNABORTED') {
        setError('Request timeout. Please try again.');
      } else {
        setError('Network error. Please check your connection.');
      }
      
      console.error('[FollowButton] UI rolled back to:', previousState);
    } finally {
      setIsLoading(false);
    }
  }
  
  /**
   * Render the button with proper state indicators
   */
  if (isFollowing === null) {
    return (
      <button className="follow-button follow-button--loading" disabled>
        <span className="spinner"></span> Loading...
      </button>
    );
  }
  
  return (
    <div className="follow-button-container">
      <button
        className={`follow-button ${isFollowing ? 'follow-button--following' : 'follow-button--follow'}`}
        onClick={handleFollowClick}
        disabled={isLoading}
        aria-label={isFollowing ? 'Unfollow' : 'Follow'}
        title={error || ''}
      >
        {isLoading ? (
          <>
            <span className="spinner"></span>
            {isFollowing ? 'Unfollowing...' : 'Following...'}
          </>
        ) : (
          isFollowing ? 'Following' : 'Follow'
        )}
      </button>
      
      {error && (
        <div className="follow-button-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

/**
 * COMPONENT IMPROVEMENTS SUMMARY:
 * 
 * 1. State Management:
 *    - isFollowing: the actual state from server
 *    - isLoading: prevents concurrent requests
 *    - error: user feedback
 * 
 * 2. Initial Load:
 *    - fetchFollowStatus() queries API on mount
 *    - Matches server state, no optimistic assumptions
 * 
 * 3. User Actions:
 *    - handleFollowClick() only triggers if not already loading
 *    - Saves previous state for rollback
 *    - Waits for HTTP 200 before updating UI
 *    - Rolls back on any error (500, timeout, network)
 *    - Shows loading spinner during request
 * 
 * 4. Error Handling:
 *    - Different messages for different error types
 *    - User stays informed
 *    - UI state reverts on failure
 * 
 * 5. Tenant Isolation:
 *    - tenantId passed to all API calls
 *    - Prevents cross-tenant operations
 * 
 * ADDRESSES:
 * - delayed_backend_confirmation: waits for 200 before UI update
 * - ui_desync_cache_delay: fetches fresh status on load
 * - concurrent_toggle_race: isLoading prevents rapid clicks
 * - cross_tenant_visibility: tenant_id in API endpoints
 */

// CSS for styling
const styles = `
.follow-button {
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 600;
  border: 1px solid #ccc;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.follow-button--follow {
  background-color: #0066cc;
  color: white;
  border-color: #0066cc;
}

.follow-button--follow:hover:not(:disabled) {
  background-color: #0052a3;
  border-color: #0052a3;
}

.follow-button--following {
  background-color: #e0e0e0;
  color: #333;
  border-color: #999;
}

.follow-button--following:hover:not(:disabled) {
  background-color: #d0d0d0;
}

.follow-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.follow-button--loading {
  background-color: #f0f0f0;
  color: #999;
}

.spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid #f0f0f0;
  border-top: 2px solid #0066cc;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
  margin-right: 4px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.follow-button-error {
  color: #d32f2f;
  font-size: 12px;
  margin-top: 4px;
  padding: 4px 8px;
  background-color: #ffebee;
  border-radius: 2px;
  border-left: 2px solid #d32f2f;
}

.follow-button-container {
  position: relative;
  display: inline-block;
}
`;

export default FollowButton;
