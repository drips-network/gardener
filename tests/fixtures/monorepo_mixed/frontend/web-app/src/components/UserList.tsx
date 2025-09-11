import React from 'react';
import { Table } from 'antd';
import { User } from '../types';

interface UserListProps {
    users: User[];
}

export const UserList: React.FC<UserListProps> = ({ users }) => {
    const columns = [
        {
            title: 'ID',
            dataIndex: 'id',
            key: 'id',
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
        },
        {
            title: 'Email',
            dataIndex: 'email',
            key: 'email',
        },
    ];

    return (
        <Table
            dataSource={users}
            columns={columns}
            rowKey="id"
            pagination={{ pageSize: 10 }}
        />
    );
};