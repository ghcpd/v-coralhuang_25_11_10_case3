// Simplified React-like component pseudocode for the Follow button
// In a real app this would be used inside a React project. Here it's a reference implementation
// showing the recommended behavior: no unconditional optimistic commit, show loading state,
// rollback UI on failure.

import React, { useState } from 'react';
import axios from 'axios';

export default function FollowButton({ tenantId, followerId, followedId, initialFollowing }) {
  const [following, setFollowing] = useState(initialFollowing);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleFollow = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await axios.post('/api/follow', { tenant_id: tenantId, follower_id: followerId, followed_id: followedId });
      if (resp.status === 200) {
        setFollowing(true);
      } else {
        setError('Follow failed');
      }
    } catch (e) {
      setError('Follow failed');
    } finally {
      setLoading(false);
    }
  };

  const handleUnfollow = async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await axios.post('/api/unfollow', { tenant_id: tenantId, follower_id: followerId, followed_id: followedId });
      if (resp.status === 200) {
        setFollowing(false);
      } else {
        setError('Unfollow failed');
      }
    } catch (e) {
      setError('Unfollow failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button onClick={() => (following ? handleUnfollow() : handleFollow())} disabled={loading}>
        {loading ? 'Processing...' : (following ? 'Following' : 'Follow')}
      </button>
      {error && <div className="error">{error}</div>}
    </div>
  );
}
