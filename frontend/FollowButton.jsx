import React, { useState } from 'react'
import axios from 'axios'

export default function FollowButton({ tenantId, viewerId, targetId, initialFollowing }) {
  const [following, setFollowing] = useState(initialFollowing)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  async function toggleFollow() {
    setLoading(true)
    setError(null)
    try {
      const action = following ? 'unfollow' : 'follow'
      const res = await axios.post('/follow', {
        tenant_id: tenantId,
        follower_id: viewerId,
        followed_id: targetId,
        action,
      })
      setFollowing(res.data.following)
    } catch (e) {
      setError('Follow failed, please retry')
    } finally {
      setLoading(false)
    }
  }

  return (
    <button onClick={toggleFollow} disabled={loading} aria-pressed={following}>
      {loading ? 'Loading...' : (following ? 'Following' : 'Follow')}
      {error && <div className="error">{error}</div>}
    </button>
  )
}
