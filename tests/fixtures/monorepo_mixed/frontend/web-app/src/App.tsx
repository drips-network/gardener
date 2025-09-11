import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Button, Card } from 'antd';
import { format } from 'date-fns';
import _ from 'lodash';

// Local imports
import { ApiClient } from './services/api';
import { UserList } from './components/UserList';
import { DataDisplay } from './components/DataDisplay';
import { User, ApiResponse } from './types';

const App: React.FC = () => {
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(false);
    const apiClient = new ApiClient();

    useEffect(() => {
        fetchUsers();
    }, []);

    const fetchUsers = async () => {
        setLoading(true);
        try {
            const response = await apiClient.getUsers();
            setUsers(response.data);
        } catch (error) {
            console.error('Failed to fetch users:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleRefresh = _.debounce(() => {
        fetchUsers();
    }, 300);

    return (
        <div className="app">
            <Card title="User Management">
                <Button onClick={handleRefresh} loading={loading}>
                    Refresh
                </Button>
                <UserList users={users} />
                <DataDisplay timestamp={format(new Date(), 'yyyy-MM-dd')} />
            </Card>
        </div>
    );
};

export default App;