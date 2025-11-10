import React, {useState, useEffect} from 'react';
import axios from 'axios';

export default function FollowButton({tenantId, followerId, followedId}){
    const [following, setFollowing] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        async function load(){
            try{
                const r = await axios.get(`/follow_status/${tenantId}/${followedId}`, {params: {follower_id: followerId}});
                setFollowing(r.data.following);
            } catch (e){
                setError('Error loading status');
            }
        }
        load();
    }, [tenantId, followerId, followedId]);

    async function doFollow(){
        setLoading(true);
        setError(null);
        try{
            const r = await axios.post('/follow', {tenant_id: tenantId, follower_id: followerId, followed_id: followedId});
            setFollowing(r.data.following);
        } catch (e){
            setError('Follow failed');
        } finally {
            setLoading(false);
        }
    }

    async function doUnfollow(){
        setLoading(true);
        setError(null);
        try{
            const r = await axios.post('/unfollow', {tenant_id: tenantId, follower_id: followerId, followed_id: followedId});
            setFollowing(r.data.following);
        } catch (e){
            setError('Unfollow failed');
        } finally {
            setLoading(false);
        }
    }

    if (following === null){
        return <button disabled>Loading...</button>
    }

    return (
        <div>
            <button onClick={following ? doUnfollow : doFollow} disabled={loading}>
                {loading ? 'Wait...' : (following ? 'Following' : 'Follow') }
            </button>
            {error && <div role="alert">{error}</div>}
        </div>
    )
}
