import React from 'react';
import { Card } from 'antd';
import moment from 'moment';

interface DataDisplayProps {
    timestamp: string;
}

export const DataDisplay: React.FC<DataDisplayProps> = ({ timestamp }) => {
    const formattedTime = moment(timestamp).format('LLL');
    
    return (
        <Card size="small" style={{ marginTop: 16 }}>
            <p>Last updated: {formattedTime}</p>
        </Card>
    );
};